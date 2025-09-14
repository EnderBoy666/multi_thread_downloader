# 多线程下载器

一个使用Python编写的不限线程数的多线程下载程序，支持大文件分割下载、进度显示和文件合并功能。

## 功能特点

- **多线程下载**：支持自定义线程数，充分利用网络带宽
- **进度显示**：实时显示下载进度、速度和剩余时间
- **自动命名**：可自动从URL提取文件名
- **备选方案**：当服务器不支持断点续传时，自动切换到单线程下载

## 安装依赖

首先安装程序所需的Python依赖包：

```bash
pip install -r requirements.txt
```

## 使用方法

### 直接打开multi_thread_downloader.py就行，或者：

### 命令行参数

```bash
python multi_thread_downloader.py -u URL [选项]
```

| 参数 | 简写 | 说明 |
|------|------|------|
| --url | -u | 下载链接（必需） |
| --file | -f | 保存的文件名（可选，默认从URL提取） |
| --threads | -t | 线程数（可选，默认10） |
| --chunk | -c | 块大小（可选，默认1MB） |

### 使用示例

1. 使用默认参数下载文件：
   ```bash
   python multi_thread_downloader.py -u https://example.com/file.zip
   ```

2. 指定线程数和文件名：
   ```bash
   python multi_thread_downloader.py -u https://example.com/file.zip -f save_as.zip -t 20
   ```

3. 自定义块大小：
   ```bash
   python multi_thread_downloader.py -u https://example.com/file.zip -c 2097152  # 2MB块大小
   ```

## 注意事项

1. 请确保目标服务器支持断点续传功能，否则程序会自动切换到单线程下载
2. 过多的线程数可能会导致服务器拒绝请求，请根据实际情况调整
3. 下载完成后，临时文件会自动删除

## 修改最大线程数

当前程序的最大线程数限制为10000。如果需要修改这个限制，请按照以下步骤操作：

1. 打开`multi_thread_downloader.py`文件
2. 找到输入验证函数中的线程数限制代码（第289行左右）：
   ```python
   def validate_threads(new_value):
       # ...
       return num > 0 and num <= 10000  # 限制线程数在1-10000之间
   ```
   将`num <= 10000`条件修改为您需要的最大线程数
3. 同时修改GUI界面的提示文本（第301行左右）：
   ```python
   ttk.Label(threads_frame, text="(1-10000之间的整数)", font=self.font).pack(anchor=tk.W, pady=(2, 0))
   ```
   将`(1-10000之间的整数)`更新为您设置的范围
4. 确保错误检查条件（第384行左右）中的：
   ```python
   if threads <= 0 or threads > 10000:
   ```
   也被相应更新

**注意：** 设置过高的线程数可能会导致系统资源耗尽或被服务器拒绝连接，请谨慎调整。