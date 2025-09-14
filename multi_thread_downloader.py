import os
import sys
import threading
import requests
import time
from tqdm import tqdm
import argparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

class MultiThreadDownloader:
    def __init__(self, url, file_name=None, threads=10, chunk_size=1024*1024, save_dir=None):
        """初始化多线程下载器
        参数:
            url (str): 下载链接
            file_name (str): 保存的文件名，默认从URL提取
            threads (int): 线程数，默认为10
            chunk_size (int): 每个块的大小，默认为1MB
            save_dir (str): 保存目录，默认使用当前目录或从file_name中提取
        """
        self.url = url
        self.threads = threads
        self.chunk_size = chunk_size
        self.file_size = 0
        self.lock = threading.Lock()
        self.completed = 0
        self.progress_bar = None
        self.gui_progress_var = None
        
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
    
    def _download_chunk(self, start, end, thread_id):
        """下载文件的一个块
        参数:
            start (int): 块的开始位置
            end (int): 块的结束位置
            thread_id (int): 线程ID
        """
        headers = {'Range': f'bytes={start}-{end}'}
        try:
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            if response.status_code in [200, 206]:  # 200: 正常, 206: 部分内容
                # 在保存目录中创建part文件
                part_file_path = os.path.join(self.save_dir, f'{os.path.basename(self.file_name)}.part{thread_id}')
                with open(part_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            with self.lock:
                                self.completed += len(chunk)
                                if self.progress_bar:
                                    self.progress_bar.update(len(chunk))
                                if self.gui_progress_var:
                                    percentage = (self.completed / self.file_size) * 100 if self.file_size > 0 else 0
                                    self.gui_progress_var.set(percentage)
            else:
                print(f"线程 {thread_id} 下载失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"线程 {thread_id} 发生错误: {e}")
    
    def _merge_parts(self):
        """合并所有下载的部分"""
        print(f"正在合并文件到: {self.file_name}")
        print(f"保存目录: {self.save_dir}")
        try:
            # 确保使用完整路径保存最终文件
            with open(self.file_name, 'wb') as f:
                for i in range(self.threads):
                    # 从保存目录中读取part文件
                    part_file_path = os.path.join(self.save_dir, f'{os.path.basename(self.file_name)}.part{i}')
                    print(f"读取part文件: {part_file_path}")
                    if os.path.exists(part_file_path):
                        with open(part_file_path, 'rb') as pf:
                            f.write(pf.read())
                        os.remove(part_file_path)
                        print(f"已删除: {part_file_path}")
                    else:
                        print(f"未找到part文件: {part_file_path}")
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
        
        # 检查是否支持断点续传
        if not self._get_file_size():  # 如果无法获取文件大小
            print("无法获取文件大小，尝试单线程下载...")
            result = self._single_thread_download()
            if self.gui_progress_var:
                self.gui_progress_var.set(100)
            return result
        
        # 计算每个线程下载的大小
        chunk_size_per_thread = self.file_size // self.threads
        
        print(f"文件名: {os.path.basename(self.file_name)}")
        print(f"保存目录: {self.save_dir}")
        print(f"文件大小: {self.file_size / (1024*1024):.2f} MB")
        print(f"线程数: {self.threads}")
        
        # 创建进度条
        if not self.gui_progress_var:
            self.progress_bar = tqdm(total=self.file_size, unit='B', unit_scale=True, desc=os.path.basename(self.file_name))
        
        # 创建线程列表
        threads = []
        start_time = time.time()
        
        # 启动所有线程
        for i in range(self.threads):
            start = i * chunk_size_per_thread
            # 最后一个线程下载剩余的所有数据
            end = self.file_size - 1 if i == self.threads - 1 else (i + 1) * chunk_size_per_thread - 1
            
            thread = threading.Thread(target=self._download_chunk, args=(start, end, i))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 关闭进度条
        if self.progress_bar:
            self.progress_bar.close()
        
        # 合并文件
        result = False
        part_files_exist = True
        for i in range(self.threads):
            part_file_path = os.path.join(self.save_dir, f'{os.path.basename(self.file_name)}.part{i}')
            if not os.path.exists(part_file_path):
                part_files_exist = False
                break
        
        if part_files_exist:
            result = self._merge_parts()
        else:
            print("下载不完整，部分文件块缺失")
            print("尝试合并可用的文件块...")
            # 即使文件不完整，也尝试合并并删除已有的part文件
            temp_result = self._merge_parts()
            
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
            response = requests.get(self.url, stream=True)
            with open(self.file_name, 'wb') as f:
                total_size = 0
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        total_size += len(chunk)
                        if self.progress_bar:
                            self.progress_bar.update(len(chunk))
                        if self.gui_progress_var:
                            # 因为不知道总大小，所以这里不更新百分比
                            pass
                        sys.stdout.write(f'\r下载进度: {total_size / (1024*1024):.2f} MB')
                        sys.stdout.flush()
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
                downloader = MultiThreadDownloader(url, file_name, threads, save_dir=save_dir)
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