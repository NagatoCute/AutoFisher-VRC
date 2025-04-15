import os
import time
import threading
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
        
        self.setup_ui()
        self.log_handler = VRChatLogHandler(self.fish_on_hook)
        self.log_handler.start_monitor()
        self.send_click(False)

        self.first_cast = True

    def toggle(self):
        self.running = not self.running
        self.start_btn.config(text="停止" if self.running else "开始")
        if self.running:
            self.first_cast = True  # 重置首次抛竿标志
            self.current_action = "开始抛竿"
            self.update_status()
            threading.Thread(target=self.perform_cast).start()
        else:
            self.emergency_release()

    def emergency_release(self):
        self.send_click(False)
        self.current_action = "已停止"
        self.update_status()

    def setup_ui(self):
        self.root.title("自动钓鱼v1.4.2")
        
        params_frame = Frame(self.root)
        params_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=2)
        
        row_counter = 0
        Label(params_frame, text="蓄力时间 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.cast_time = Entry(params_frame)
        self.cast_time.insert(0, "2")
        self.cast_time.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="休息时间 (秒):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.rest_time = Entry(params_frame)
        self.rest_time.insert(0, "3")
        self.rest_time.grid(row=row_counter, column=1, padx=5, pady=2)
        row_counter += 1

        Label(params_frame, text="超时重钓 (分):").grid(row=row_counter, padx=5, pady=2, sticky=W)
        self.timeout_limit = Entry(params_frame)
        self.timeout_limit.insert(0, "5")
        self.timeout_limit.grid(row=row_counter, column=1, padx=5, pady=2)

        control_frame = Frame(self.root)
        control_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        self.start_btn = Button(control_frame, text="开始", command=self.toggle, width=8)
        self.start_btn.pack(side=LEFT, padx=(0, 10))
        
        self.status_label = Label(control_frame, text="[开发者arcxingye]", width=15, anchor=W)
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
        if self.timeout_timer and self.timeout_timer.is_alive():
            self.timeout_timer.cancel()
        
        timeout = self.get_param(self.timeout_limit, 5) * 60
        self.timeout_timer = threading.Timer(timeout, self.handle_timeout)
        self.timeout_timer.start()

    def handle_timeout(self):
        if self.running and self.current_action == "等待上钩":
            self.current_action = "超时收杆"
            self.update_status()
            self.force_reel()

    def force_reel(self):
        if self.protected:
            return

        try:
            self.protected = True
            self.perform_reel()
            self.perform_cast()
        finally:
            self.protected = False

    def check_fish_pickup(self):
        start_time = time.time()
        self.detected_time = None
        
        while time.time() - start_time < 30:
            content = self.log_handler.safe_read_file()
            
            if "Fish Pickup attached to rod Toggles(True)" in content:
                if not self.detected_time:
                    self.detected_time = time.time()
                    
            if self.detected_time and (time.time() - self.detected_time >= 2):
                return True
                
            time.sleep(0.5)
            
        return False

    def perform_reel(self):
        self.current_action = "收杆中"
        self.update_status()
        self.send_click(True)
        
        success = self.check_fish_pickup()
        
        if success and self.detected_time:
            elapsed = time.time() - self.detected_time
            remaining_time = max(0, 2 - elapsed)
            if remaining_time > 0:
                time.sleep(remaining_time)
        
        self.send_click(False)
        self.detected_time = None

    def perform_cast(self):
        if not self.first_cast:
            # 只有非首次抛竿才需要休息
            self.current_action = "休息中"
            self.update_status()
            try:
                rest_duration = float(self.rest_time.get())
            except:
                rest_duration = 3.0
            time.sleep(max(0.1, rest_duration))
        else:
            self.first_cast = False  # 标记首次抛竿完成

        # 蓄力抛竿
        self.current_action = "鱼竿蓄力中"
        self.update_status()
        cast_duration = self.get_param(self.cast_time, 2)
        self.send_click(True)
        time.sleep(cast_duration)
        self.send_click(False)

        # 抛竿后等待
        self.current_action = "等待鱼上钩"
        self.update_status()
        self.start_timeout_timer()
        time.sleep(3)

    def fish_on_hook(self):
        if not self.running or self.protected or time.time() - self.last_cycle_end < 2:
            return

        try:
            self.protected = True
            self.last_cycle_end = time.time()
            self.perform_reel()
            self.perform_cast()
        finally:
            self.protected = False
            self.last_cycle_end = time.time()

    def on_close(self):
        self.emergency_release()
        try:
            if hasattr(self, 'timeout_timer') and self.timeout_timer:
                self.timeout_timer.cancel()
            
            if self.observer.is_alive():
                self.observer.stop()
                self.observer.join(timeout=1)
            
            if hasattr(self.log_handler, 'check_thread'):
                self.log_handler.check_thread.join(timeout=0.5)
                
        except Exception as e:
            print(f"关闭时发生错误: {e}")
        finally:
            self.root.destroy()
            self.root.quit()

if __name__ == "__main__":
    root = Tk()
    app = AutoFishingApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
