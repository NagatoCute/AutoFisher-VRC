import os
import time
import threading
from tkinter import *
from pythonosc import udp_client
from tkinter import font as tkFont
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
        self.root.title("自动钓鱼v1.5.0-alhpa.1")
        self.root.geometry("300x270")
        self.root.resizable(False, False)
        self.colors = {
            "bg": "#0A2463",
            "fg": "#D8F3DC",
            "frame_bg": "#1E4299",
            "entry_bg": "#0A2463",
            "entry_fg": "#90E0EF",
            "button_bg": "#3B82F6",
            "button_fg": "#FFFFFF",
            "button_active_bg": "#2563EB",
            "label_fg": "#D8F3DC",
            "status": {
                "default": "#FFFFFF",
                "running": "#70e000",
                "waiting": "#00b4d8",
                "action": "#ffdd00",
                "stopped": "#ef233c"
            }
        }

        self.root.config(bg=self.colors["bg"])

        main_font = tkFont.Font(family="Verdana", size=10)
        status_font = tkFont.Font(family="Verdana", size=11, weight="bold")
        button_font = tkFont.Font(family="Verdana", size=10, weight="bold")

        params_frame = Frame(self.root, bg=self.colors["frame_bg"], padx=15, pady=10,
                             borderwidth=1, relief=SOLID)
        params_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.root.columnconfigure(0, weight=1)

        params_frame.columnconfigure(1, weight=1)

        def create_param_entry(parent, text, default_value, row):
            Label(parent, text=text, bg=self.colors["frame_bg"], fg=self.colors["label_fg"], font=main_font).grid(
                row=row, column=0, padx=5, pady=6, sticky=W)
            entry = Entry(parent, width=9, bg=self.colors["entry_bg"], fg=self.colors["entry_fg"], font=main_font,
                          relief=FLAT, insertbackground=self.colors["fg"], highlightthickness=2,
                          highlightbackground=self.colors["frame_bg"], highlightcolor=self.colors["button_bg"])
            entry.insert(0, default_value)
            entry.grid(row=row, column=1, padx=5, pady=6, sticky=E)
            return entry

        self.cast_time = create_param_entry(params_frame, "蓄力时间 (秒):", "2", 0)
        self.rest_time = create_param_entry(params_frame, "休息时间 (秒):", "3", 1)
        self.reel_time = create_param_entry(params_frame, "收杆时间 (秒):", "2", 2)
        self.timeout_limit = create_param_entry(params_frame, "超时重钓 (分):", "5", 3)

        control_frame = Frame(self.root, bg=self.colors["bg"], pady=5)
        control_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        control_frame.columnconfigure(1, weight=1)

        self.start_btn = Button(control_frame, text="开始", command=self.toggle, font=button_font,
                                bg=self.colors["button_bg"], fg=self.colors["button_fg"],
                                activebackground=self.colors["button_active_bg"],
                                activeforeground=self.colors["button_fg"],
                                relief=RAISED, borderwidth=1, width=12, height=2)
        self.start_btn.grid(row=0, column=0, padx=(0, 15))

        self.status_label = Label(control_frame, text="[开发者 arcxingye]",
                                  font=status_font, bg=self.colors["bg"], fg=self.colors["status"]["default"],
                                  width=18,
                                  anchor=W)
        self.status_label.grid(row=0, column=1, sticky="ew")

    def update_status(self):
        if not hasattr(self, 'status_label'): return

        status_text = self.current_action
        color = self.colors["status"]["default"]
        if "上钩" in status_text or "等待" in status_text:
            color = self.colors["status"]["waiting"]
        elif "收杆" in status_text or "蓄力" in status_text or "抛竿" in status_text:
            color = self.colors["status"]["action"]
        elif "停止" in status_text or "超时" in status_text:
            color = self.colors["status"]["stopped"]
        elif self.running:
            color = self.colors["status"]["running"]

        self.root.after(0, self.status_label.config, {'text': f"[{status_text}]", 'fg': color})

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
        # 获取 UI 设置的收杆时间（默认2秒）
        reel_duration = self.get_param(self.reel_time, 2)
        success = self.check_fish_pickup()

        if success and self.detected_time:
            elapsed = time.time() - self.detected_time
            remaining_time = max(0, reel_duration - elapsed)
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
