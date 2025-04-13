import os
import time
import random
import threading
import keyboard
from tkinter import *
from pythonosc import udp_client
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class VRChatLogHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.current_log = None
        self.last_check = 0
        self.lock = threading.Lock()
        self.update_log_file()

    def get_vrchat_log_dir(self):
        appdata = os.getenv('APPDATA', '')
        return os.path.normpath(os.path.join(
            appdata, r'..\LocalLow\VRChat\VRChat'
        ))

    def find_latest_log(self):
        log_dir = self.get_vrchat_log_dir()
        if not os.path.exists(log_dir):
            return None
            
        logs = [f for f in os.listdir(log_dir) 
               if f.startswith('output_log_') and f.endswith('.txt')]
        if not logs:
            return None
            
        latest = max(
            logs,
            key=lambda x: os.path.getmtime(os.path.join(log_dir, x))
        )
        return os.path.join(log_dir, latest)

    def update_log_file(self):
        new_log = self.find_latest_log()
        if new_log != self.current_log:
            print(f"检测到新日志文件: {new_log}")
            self.current_log = new_log
            self.file_position = 0
            return True
        return False

    def safe_read_file(self):
        if not self.current_log or not os.path.exists(self.current_log):
            return ''
            
        try:
            with open(self.current_log, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, 2)
                file_size = f.tell()
                
                if self.file_position > file_size:
                    self.file_position = 0
                    
                f.seek(self.file_position)
                content = f.read()
                self.file_position = f.tell()
                return content
        except Exception as e:
            print(f"读取日志失败: {str(e)}")
            return ''

    def check_logs(self):
        while True:
            time.sleep(1)
            if self.update_log_file():
                continue
                
            content = self.safe_read_file()
            if "SAVED DATA" in content:
                self.callback()

    def start_monitor(self):
        self.observer = Observer()
        self.observer.schedule(self, path=self.get_vrchat_log_dir(), recursive=False)
        self.observer.start()
        
        # 启动独立检测线程
        self.check_thread = threading.Thread(target=self.check_logs, daemon=True)
        self.check_thread.start()

class AutoFishingApp:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.current_action = "等待"
        self.protected = False
        self.last_cycle_end = 0
        self.timeout_timer = None
        self.osc_client = udp_client.SimpleUDPClient("127.0.0.1", 9000)
        self.last_toggle_time = 0  # 用于防抖

        self.setup_ui()
        self.log_handler = VRChatLogHandler(self.fish_on_hook)
        self.log_handler.start_monitor()

        self.send_click(False)
        
        # 使用 keyboard 库监听全局 F5 键，添加防抖
        keyboard.on_press_key('f5', self.handle_f5)

    def handle_f5(self, event):
        """处理 F5 按键事件，添加防抖逻辑"""
        current_time = time.time()
        if current_time - self.last_toggle_time < 0.5:  # 防抖：0.5秒内只触发一次
            return
        self.last_toggle_time = current_time
        self.toggle()

    def toggle(self):
        self.running = not self.running
        self.start_btn.config(text="停止" if self.running else "开始")
        if not self.running:
            self.emergency_release()
            # 重置保护状态和动作状态，防止后续自动抛竿
            self.protected = False
            self.current_action = "已停止"
            self.last_cycle_end = time.time()
            # 取消所有定时器
            if self.timeout_timer and self.timeout_timer.is_alive():
                self.timeout_timer.cancel()
                self.timeout_timer = None
        else:
            self.current_action = "等待"
        self.update_status()

    def emergency_release(self):
        self.send_click(False)
        self.current_action = "已停止"
        self.update_status()

    def setup_ui(self):
        self.root.title("自动钓鱼v1.3 By arcxingye")
        
        params_frame = Frame(self.root)
        params_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=2)
        
        row_counter = 0
        Label(params_frame, text="收杆时间 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.reel_time = Entry(params_frame)
        self.reel_time.insert(0, "20")
        self.reel_time.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="休息时间 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.rest_time = Entry(params_frame)
        self.rest_time.insert(0, "2")
        self.rest_time.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="蓄力时间 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.cast_time = Entry(params_frame)
        self.cast_time.insert(0, "2")
        self.cast_time.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="抛竿后等待 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.post_cast_wait = Entry(params_frame)
        self.post_cast_wait.insert(0, "3")
        self.post_cast_wait.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="超时时间 (分钟):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.timeout_limit = Entry(params_frame)
        self.timeout_limit.insert(0, "5")
        self.timeout_limit.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="随机范围 (±秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.random_range = Entry(params_frame)
        self.random_range.insert(0, "0.5")
        self.random_range.grid(row=row_counter, column=1, padx=5, pady=2)

        control_frame = Frame(self.root)
        control_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        self.start_btn = Button(control_frame, text="开始", command=self.toggle, width=8)
        self.start_btn.pack(side=LEFT, padx=(0, 10))
        
        self.status_label = Label(control_frame, text="[等待]", width=15, anchor=W)
        self.status_label.pack(side=LEFT)

    def update_status(self):
        self.status_label.config(text=f"[{self.current_action}]")
        self.root.update()

    def send_click(self, press):
        self.osc_client.send_message("/input/UseRight", 1 if press else 0)

    def get_param(self, entry, default):
        try:
            value = float(entry.get())
            return max(0.5, value)
        except:
            return max(0.5, default)

    def start_timeout_timer(self):
        """启动超时计时器"""
        if self.timeout_timer and self.timeout_timer.is_alive():
            self.timeout_timer.cancel()
        
        timeout = self.get_param(self.timeout_limit, 5) * 60  # 转换为秒
        self.timeout_timer = threading.Timer(timeout, self.handle_timeout)
        self.timeout_timer.start()

    def handle_timeout(self):
        """超时处理函数"""
        if self.running and self.current_action == "等待上钩":
            self.current_action = "超时收杆"
            self.update_status()
            self.force_reel()

    def force_reel(self):
        """强制收杆流程"""
        if self.protected:
            return

        try:
            self.protected = True
            # 执行收杆操作
            self.perform_reel()
            # 重新抛竿
            self.perform_cast()
        finally:
            self.protected = False

    def perform_reel(self):
        """收杆流程"""
        self.current_action = "收杆中"
        self.update_status()
        reel_duration = self.get_param(self.reel_time, 20) + random.uniform(
            -self.get_param(self.random_range, 0.5),
            self.get_param(self.random_range, 0.5)
        )
        self.send_click(True)
        time.sleep(reel_duration)
        self.send_click(False)

    def perform_cast(self):
        """抛竿流程"""
        # 休息阶段
        self.current_action = "休息中"
        self.update_status()
        rest_duration = self.get_param(self.rest_time, 2) + random.uniform(
            -self.get_param(self.random_range, 0.5),
            self.get_param(self.random_range, 0.5)
        )
        time.sleep(rest_duration)

        # 蓄力抛竿
        self.current_action = "蓄力中"
        self.update_status()
        cast_duration = self.get_param(self.cast_time, 2)
        self.send_click(True)
        time.sleep(cast_duration)
        self.send_click(False)

        # 抛竿后等待
        self.current_action = "等待上钩"
        self.update_status()
        self.start_timeout_timer()  # 启动超时计时器
        post_wait = self.get_param(self.post_cast_wait, 3)
        time.sleep(post_wait)

    def fish_on_hook(self):
        if not self.running or self.protected or time.time() - self.last_cycle_end < 2:
            return

        try:
            self.protected = True
            self.last_cycle_end = time.time()
            
            # 再次检查运行状态，避免在关闭后仍继续执行
            if not self.running:
                return
                
            # 正常收杆流程
            self.perform_reel()
            
            # 再次检查运行状态，避免抛竿
            if not self.running:
                return
                
            # 执行抛竿流程
            self.perform_cast()
            
        finally:
            self.protected = False
            self.last_cycle_end = time.time()

    def on_close(self):
        self.emergency_release()
        try:
            # 停止所有定时器
            if hasattr(self, 'timeout_timer') and self.timeout_timer:
                self.timeout_timer.cancel()
            
            # 停止日志观察者
            if self.observer.is_alive():
                self.observer.stop()
                self.observer.join(timeout=1)  # 最多等待1秒
            
            # 停止日志检测线程
            if hasattr(self.log_handler, 'check_thread'):
                self.log_handler.check_thread.join(timeout=0.5)
                
            # 清理 keyboard 监听
            keyboard.unhook_all()
                
        except Exception as e:
            print(f"关闭时发生错误: {e}")
        finally:
            self.root.destroy()
            self.root.quit()  # 强制终止 Tkinter 主循环

if __name__ == "__main__":
    root = Tk()
    app = AutoFishingApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
