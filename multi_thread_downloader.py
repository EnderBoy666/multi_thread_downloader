import os
import sys
import threading
import requests
import time
from tqdm import tqdm
import argparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import queue

class MultiThreadDownloader:
    def __init__(self, url, file_name=None, threads=10, chunk_size=1024*1024, save_dir=None, timeout=60):
        """初始化多线程下载器
        参数:
            url (str): 下载链接
            file_name (str): 保存的文件名，默认从URL提取
            threads (int): 线程数，默认为10
            chunk_size (int): 每个块的大小，默认为1MB
            save_dir (str): 保存目录，默认使用当前目录或从file_name中提取
            timeout (int): 线程超时时间(秒)，默认为60秒
        """
        self.url = url
        self.threads = threads
        self.chunk_size = chunk_size
        self.file_size = 0
        self.lock = threading.Lock()
        self.completed = 0
        self.progress_bar = None
        self.gui_progress_var = None
        self.timeout = timeout
        # 任务队列
        self.task_queue = queue.Queue()
        # 线程状态跟踪
        self.thread_status = {}
        # 任务是否完成标志
        self.is_completed = False
        # 线程最后活动时间
        self.last_activity = {}
        # 启动超时检测线程
        self.timeout_thread = None
        
        # 处理保存目录和文件名
        if save_dir:
            self.save_dir = os.path.abspath(save_dir)
            # 确保保存目录存在
            os.makedirs(self.save_dir, exist_ok=True)
            
            if file_name:
                # 如果提供了文件名，将其放在指定目录下
                self.file_name = os.path.join(self.save_dir, os.path.basename(file_name))
            else:
                # 如果没有提供文件名，从URL提取并放在指定目录下
                self.file_name = os.path.join(self.save_dir, self._get_file_name_from_url())
        else:
            if file_name:
                # 如果提供了文件名，使用它的目录
                self.file_name = os.path.abspath(file_name)
                self.save_dir = os.path.dirname(self.file_name)
            else:
                # 如果都没有提供，使用当前目录
                self.save_dir = os.getcwd()
                self.file_name = os.path.join(self.save_dir, self._get_file_name_from_url())
        
    def _get_file_name_from_url(self):
        """从URL中提取文件名"""
        import re
        file_name = re.findall(r'[^/]+$', self.url.split('?')[0])[0]
        return file_name
    
    def _get_file_size(self):
        """获取文件大小"""
        try:
            response = requests.head(self.url, allow_redirects=True)
            if 'Content-Length' in response.headers:
                self.file_size = int(response.headers['Content-Length'])
                return True
            return False
        except Exception as e:
            print(f"获取文件大小失败: {e}")
            return False
    
    def _download_chunk(self, thread_id):
        """从任务队列中获取任务并下载
        参数:
            thread_id (int): 线程ID
        """
        # 初始化线程状态
        with self.lock:
            self.thread_status[thread_id] = 'running'
            self.last_activity[thread_id] = time.time()
            
        try:
            while not self.is_completed:
                try:
                    # 从队列获取任务，如果队列为空则等待
                    start, end, task_id = self.task_queue.get(timeout=1)  # 1秒超时，以便定期检查任务完成状态
                    
                    with self.lock:
                        self.last_activity[thread_id] = time.time()
                        print(f"线程 {thread_id} 开始处理任务 {task_id}: {start}-{end}")
                    
                    headers = {'Range': f'bytes={start}-{end}'}
                    response = requests.get(self.url, headers=headers, stream=True, timeout=self.timeout)
                    
                    if response.status_code in [200, 206]:  # 200: 正常, 206: 部分内容
                        # 在保存目录中创建part文件
                        part_file_path = os.path.join(self.save_dir, f'{os.path.basename(self.file_name)}.part{task_id}')
                        with open(part_file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=self.chunk_size):
                                if chunk:
                                    f.write(chunk)
                                    with self.lock:
                                        self.completed += len(chunk)
                                        self.last_activity[thread_id] = time.time()
                                        if self.progress_bar:
                                            self.progress_bar.update(len(chunk))
                                        if self.gui_progress_var:
                                            percentage = (self.completed / self.file_size) * 100 if self.file_size > 0 else 0
                                            self.gui_progress_var.set(percentage)
                    else:
                        print(f"线程 {thread_id} 任务 {task_id} 下载失败: HTTP {response.status_code}")
                        # 将失败的任务重新加入队列
                        with self.lock:
                            self.task_queue.put((start, end, task_id))
                    
                    # 标记任务完成
                    self.task_queue.task_done()
                    
                except queue.Empty:
                    # 队列为空，检查是否所有任务都已完成
                    if self.task_queue.empty() and self.completed >= self.file_size and self.file_size > 0:
                        with self.lock:
                            self.is_completed = True
                        break
                except Exception as e:
                    print(f"线程 {thread_id} 发生错误: {e}")
                    # 如果有任务在处理中，将其重新加入队列
                    if 'start' in locals() and 'end' in locals() and 'task_id' in locals():
                        with self.lock:
                            self.task_queue.put((start, end, task_id))
                    # 短暂休息后继续尝试
                    time.sleep(1)
        finally:
            with self.lock:
                self.thread_status[thread_id] = 'stopped'
    
    def _check_timeouts(self):
        """检查线程超时并重新分配任务"""
        while not self.is_completed:
            time.sleep(10)  # 每10秒检查一次
            current_time = time.time()
            
            with self.lock:
                # 检查哪些线程超时
                for thread_id, last_time in list(self.last_activity.items()):
                    if (current_time - last_time > self.timeout and 
                        self.thread_status.get(thread_id) == 'running'):
                        print(f"线程 {thread_id} 超时({current_time - last_time:.2f}秒)，将重新分配其任务")
                        # 将该线程标记为超时
                        self.thread_status[thread_id] = 'timeout'
                        # 这里不直接终止线程，而是让其自行结束
                        # 线程在下次尝试获取任务时会发现状态变化
        
    def _merge_parts(self):
        """合并所有下载的部分"""
        print(f"正在合并文件到: {self.file_name}")
        print(f"保存目录: {self.save_dir}")
        try:
            # 确保使用完整路径保存最终文件
            with open(self.file_name, 'wb') as f:
                # 查找所有的part文件
                part_files = []
                for i in range(self.threads * 2):  # 考虑可能的重新分配任务
                    part_file_path = os.path.join(self.save_dir, f'{os.path.basename(self.file_name)}.part{i}')
                    if os.path.exists(part_file_path):
                        part_files.append((part_file_path, i))
                
                # 按任务ID排序后合并
                for part_file_path, task_id in sorted(part_files, key=lambda x: x[1]):
                    print(f"读取part文件: {part_file_path}")
                    with open(part_file_path, 'rb') as pf:
                        f.write(pf.read())
                    os.remove(part_file_path)
                    print(f"已删除: {part_file_path}")
            print(f"文件 {self.file_name} 下载完成!")
            return True
        except Exception as e:
            print(f"合并文件失败: {str(e)}")
            print(f"尝试保存到的路径: {self.file_name}")
            return False
    
    def download(self, gui_progress_var=None):
        """开始下载文件
        参数:
            gui_progress_var: GUI进度条变量，用于更新进度
        """
        self.gui_progress_var = gui_progress_var
        self.is_completed = False
        self.completed = 0
        
        # 清空任务队列
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
                self.task_queue.task_done()
            except queue.Empty:
                break
        
        # 重置线程状态
        self.thread_status = {}
        self.last_activity = {}
        
        # 检查是否支持断点续传
        if not self._get_file_size():  # 如果无法获取文件大小
            print("无法获取文件大小，尝试单线程下载...")
            result = self._single_thread_download()
            if self.gui_progress_var:
                self.gui_progress_var.set(100)
            return result
        
        # 计算每个任务的大小（比线程数多一些任务，以便更好地处理超时）
        task_size = self.file_size // (self.threads * 2)  # 每个任务的大小
        if task_size == 0:
            task_size = 1  # 确保任务大小至少为1
        
        # 创建任务队列
        task_id = 0
        current_position = 0
        while current_position < self.file_size:
            start = current_position
            end = min(current_position + task_size - 1, self.file_size - 1)
            self.task_queue.put((start, end, task_id))
            current_position = end + 1
            task_id += 1
        
        print(f"文件名: {os.path.basename(self.file_name)}")
        print(f"保存目录: {self.save_dir}")
        print(f"文件大小: {self.file_size / (1024*1024):.2f} MB")
        print(f"线程数: {self.threads}")
        print(f"任务数: {task_id}")
        print(f"超时设置: {self.timeout}秒")
        
        # 创建进度条
        if not self.gui_progress_var:
            self.progress_bar = tqdm(total=self.file_size, unit='B', unit_scale=True, desc=os.path.basename(self.file_name))
        
        # 创建并启动超时检测线程
        self.timeout_thread = threading.Thread(target=self._check_timeouts, daemon=True)
        self.timeout_thread.start()
        
        # 创建线程列表
        threads = []
        start_time = time.time()
        
        # 启动所有下载线程
        for i in range(self.threads):
            thread = threading.Thread(target=self._download_chunk, args=(i,))
            threads.append(thread)
            thread.daemon = True
            thread.start()
        
        # 等待任务队列完成
        while not self.is_completed and any(t.is_alive() for t in threads):
            time.sleep(1)
            # 检查是否所有线程都已停止但任务未完成
            with self.lock:
                active_threads = sum(1 for status in self.thread_status.values() if status == 'running')
                if active_threads == 0 and not self.task_queue.empty():
                    print("所有线程都已停止，但任务未完成，尝试重新启动线程...")
                    # 尝试重新启动一些线程
                    for i in range(min(5, self.threads)):  # 重新启动最多5个线程
                        thread = threading.Thread(target=self._download_chunk, args=(i + 100,))  # 使用新的线程ID
                        threads.append(thread)
                        thread.daemon = True
                        thread.start()
        
        # 设置完成标志
        self.is_completed = True
        
        # 关闭进度条
        if self.progress_bar:
            self.progress_bar.close()
        
        # 合并文件
        result = self._merge_parts()
        
        end_time = time.time()
        print(f"下载耗时: {end_time - start_time:.2f} 秒")
        if end_time - start_time > 0:
            print(f"下载速度: {self.file_size / (1024*1024 * (end_time - start_time)):.2f} MB/s")
        
        if self.gui_progress_var:
            self.gui_progress_var.set(100)
        
        return result
    
    def _single_thread_download(self):
        """单线程下载作为备选方案"""
        try:
            response = requests.get(self.url, stream=True, timeout=self.timeout)
            with open(self.file_name, 'wb') as f:
                total_size = 0
                last_activity_time = time.time()
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        total_size += len(chunk)
                        with self.lock:
                            self.completed += len(chunk)
                        if self.progress_bar:
                            self.progress_bar.update(len(chunk))
                        if self.gui_progress_var:
                            # 因为不知道总大小，所以这里不更新百分比
                            pass
                        sys.stdout.write(f'\r下载进度: {total_size / (1024*1024):.2f} MB')
                        sys.stdout.flush()
                        # 更新最后活动时间
                        last_activity_time = time.time()
                    # 检查是否超时
                    if time.time() - last_activity_time > self.timeout:
                        print("\n单线程下载超时")
                        return False
            print(f"\n文件 {self.file_name} 单线程下载完成!")
            return True
        except Exception as e:
            print(f"单线程下载失败: {e}")
            return False

class DownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("多线程下载器")
        self.root.geometry("650x400")
        self.root.resizable(True, True)
        
        # 设置中文字体
        self.font = ('SimHei', 10)
        
        # 创建主框架
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # URL输入
        url_frame = ttk.Frame(main_frame)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(url_frame, text="下载链接:", font=self.font).pack(anchor=tk.W)
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=70, font=self.font)
        url_entry.pack(fill=tk.X, expand=True)
        
        # 保存目录选择
        dir_frame = ttk.Frame(main_frame)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(dir_frame, text="保存目录:", font=self.font).pack(anchor=tk.W)
        dir_frame_inner = ttk.Frame(dir_frame)
        dir_frame_inner.pack(fill=tk.X, expand=True)
        
        self.dir_var = tk.StringVar(value=os.getcwd())
        dir_entry = ttk.Entry(dir_frame_inner, textvariable=self.dir_var, width=50, font=self.font)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        browse_dir_btn = ttk.Button(dir_frame_inner, text="浏览...", command=self.browse_dir)
        browse_dir_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # 文件名输入
        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(file_frame, text="保存文件名:", font=self.font).pack(anchor=tk.W)
        file_frame_inner = ttk.Frame(file_frame)
        file_frame_inner.pack(fill=tk.X, expand=True)
        
        self.file_var = tk.StringVar()
        file_entry = ttk.Entry(file_frame_inner, textvariable=self.file_var, width=50, font=self.font)
        file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        browse_file_btn = ttk.Button(file_frame_inner, text="浏览...", command=self.browse_file)
        browse_file_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # 线程数设置
        threads_frame = ttk.Frame(main_frame)
        threads_frame.pack(fill=tk.X, pady=(0, 10))
        
        threads_frame_inner = ttk.Frame(threads_frame)
        threads_frame_inner.pack(fill=tk.X, expand=True)
        
        ttk.Label(threads_frame_inner, text="线程数:", font=self.font).pack(side=tk.LEFT, padx=(0, 5))
        self.threads_var = tk.StringVar(value="10")  # 改为StringVar以便更好地处理输入验证
        threads_entry = ttk.Entry(threads_frame_inner, textvariable=self.threads_var, width=10, font=self.font)
        threads_entry.pack(side=tk.LEFT, padx=(0, 5))
        
        # 添加输入验证
        def validate_threads(new_value):
            if not new_value:
                return True  # 允许为空
            try:
                num = int(new_value)
                return num > 0 and num <= 10000  # 限制线程数在1-10000之间
            except ValueError:
                return False
        
        vcmd = threads_frame.register(validate_threads)
        threads_entry.config(validate="key", validatecommand=(vcmd, '%P'))
        
        ttk.Label(threads_frame, text="(1-10000之间的整数)", font=self.font).pack(anchor=tk.W, pady=(2, 0))
        
        # 进度条
        self.progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        
        progress_bar.pack(fill=tk.X, pady=(10, 10))
        
        self.progress_label = ttk.Label(main_frame, text="准备就绪", font=self.font)
        self.progress_label.pack(anchor=tk.W)
        
        # 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        start_btn = ttk.Button(btn_frame, text="开始下载", command=self.start_download)
        start_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        exit_btn = ttk.Button(btn_frame, text="退出", command=root.destroy)
        exit_btn.pack(side=tk.RIGHT)
        
        # 底部提示
        tips_frame = ttk.Frame(root)
        tips_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        tips = "提示: 包含特殊字符的URL可以直接粘贴到输入框中，无需额外处理"
        ttk.Label(tips_frame, text=tips, font=self.font, foreground="gray").pack(anchor=tk.W)
        
    def browse_dir(self):
        """浏览目录"""
        dir_name = filedialog.askdirectory(initialdir=self.dir_var.get())
        if dir_name:
            self.dir_var.set(dir_name)
    
    def browse_file(self):
        """浏览文件"""
        default_filename = ""
        if self.url_var.get():
            # 尝试从URL提取文件名
            try:
                import re
                url = self.url_var.get()
                default_filename = re.findall(r'[^/]+$', url.split('?')[0])[0]
            except:
                default_filename = ""
        
        filename = filedialog.asksaveasfilename(defaultextension="", 
                                               filetypes=[("所有文件", "*.*")],
                                               initialdir=self.dir_var.get(),
                                               initialfile=default_filename)
        if filename:
            self.file_var.set(os.path.basename(filename))
            self.dir_var.set(os.path.dirname(filename))
    
    def start_download(self):
        """开始下载"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入下载链接")
            return
        
        save_dir = self.dir_var.get().strip()
        if not save_dir:
            messagebox.showerror("错误", "请选择保存目录")
            return
        
        # 确保保存目录存在
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建保存目录: {str(e)}")
            return
        
        file_name = self.file_var.get().strip() if self.file_var.get().strip() else None
        
        # 验证线程数输入
        threads_text = self.threads_var.get().strip()
        if not threads_text:
            messagebox.showerror("错误", "请输入线程数")
            return
        
        try:
            threads = int(threads_text)
            if threads <= 0 or threads > 10000:
                messagebox.showerror("错误", "线程数必须在1-10000之间")
                return
        except ValueError:
            messagebox.showerror("错误", "请输入有效的线程数")
            return
        
        # 在新线程中开始下载，避免UI冻结
        def download_thread_func():
            self.progress_var.set(0)
            self.progress_label.config(text="正在准备下载...")
            
            try:
                # 使用默认超时60秒
                downloader = MultiThreadDownloader(url, file_name, threads, save_dir=save_dir, timeout=60)
                result = downloader.download(self.progress_var)
                
                if result:
                    self.progress_label.config(text="下载完成")
                    messagebox.showinfo("成功", f"文件已成功下载到:\n{downloader.file_name}")
                else:
                    self.progress_label.config(text="下载失败")
                    messagebox.showerror("失败", "下载过程中出现错误")
            except Exception as e:
                self.progress_label.config(text=f"下载失败: {str(e)}")
                messagebox.showerror("错误", f"下载过程中出现异常:\n{str(e)}")
        
        threading.Thread(target=download_thread_func, daemon=True).start()

def main():
    """主函数，处理命令行参数"""
    # 使用引号提示用户包裹特殊URL
    parser = argparse.ArgumentParser(
        description='多线程下载器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='注意: 当URL包含特殊字符(&, ?, =等)时，请用引号包裹整个URL\n例如: python multi_thread_downloader.py -u "https://example.com/file?param=value"'
    )
    parser.add_argument('-u', '--url', help='下载链接')
    parser.add_argument('-f', '--file', help='保存的文件名')
    parser.add_argument('-d', '--dir', help='保存目录')
    parser.add_argument('-t', '--threads', type=int, default=10, help='线程数，默认10')
    parser.add_argument('-c', '--chunk', type=int, default=1024*1024, help='块大小，默认1MB')
    parser.add_argument('--nogui', action='store_true', help='不使用GUI界面，强制使用命令行模式')
    
    args, unknown = parser.parse_known_args()
    
    # 如果指定了--nogui或提供了URL参数，则使用命令行模式
    if args.nogui or args.url:
        # 处理特殊情况：当URL被截断时尝试从剩余参数中恢复
        if unknown:
            # 重新构建完整的URL
            full_url = args.url
            for arg in unknown:
                if arg.startswith('-'):
                    # 如果是另一个参数标志，停止拼接
                    break
                full_url += ' ' + arg
            args.url = full_url
            print(f"检测到并修复了URL: {args.url}")
        
        if not args.url:
            parser.error("命令行模式需要提供URL参数 (-u/--url)")
        
        # 创建下载器并开始下载
        downloader = MultiThreadDownloader(args.url, args.file, args.threads, args.chunk, args.dir)
        downloader.download()
    else:
        # 否则使用GUI模式
        root = tk.Tk()
        app = DownloaderGUI(root)
        root.mainloop()

if __name__ == '__main__':
    main()