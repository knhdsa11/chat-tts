import os
import sys
import subprocess
import pygame
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import pytchat
import threading
import multiprocessing
import time
import queue
import shutil
from datetime import datetime

class YouTubeTTS:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube TTS Player 🎙️")
        self.root.geometry("720x520")
        self.root.configure(bg="#1e1e1e")

        self.running = False
        self.process = None
        self.voice = "th-TH-PremwadeeNeural"
        self.temp_dir = "tts_cache"

        os.makedirs(self.temp_dir, exist_ok=True)

        pygame.mixer.init()
        self.setup_ui()

        # Queue สำหรับสื่อสารกับ process
        self.manager = multiprocessing.Manager()
        self.shared_queue = self.manager.Queue()

    # ---------- UI ----------
    def setup_ui(self):
        title = tk.Label(self.root, text="🎧 YouTube Chat TTS", bg="#1e1e1e", fg="#00ffb3",
                         font=("Segoe UI", 16, "bold"))
        title.pack(pady=10)

        frame = ttk.Frame(self.root)
        frame.pack(pady=10)

        tk.Label(frame, text="YouTube Live Chat URL:", font=("Segoe UI", 10)).grid(row=0, column=0, padx=5)
        self.url_entry = ttk.Entry(frame, width=50)
        self.url_entry.grid(row=0, column=1, padx=5)

        ttk.Button(frame, text="Start", command=self.start_system).grid(row=0, column=2, padx=5)
        ttk.Button(frame, text="Stop", command=self.stop_system).grid(row=0, column=3, padx=5)
        ttk.Button(frame, text="🧹 Clear Temp", command=self.clear_temp).grid(row=0, column=4, padx=5)

        self.log_box = scrolledtext.ScrolledText(self.root, width=80, height=20, bg="#252526", fg="#d4d4d4",
                                                 insertbackground="white", font=("Consolas", 10))
        self.log_box.pack(pady=10)

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_box.see(tk.END)

    # ---------- Core ----------
    def start_system(self):
        if self.running:
            self.log("[INFO] ระบบทำงานอยู่แล้ว")
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("URL Missing", "กรุณาใส่ลิงก์ YouTube Live Chat ก่อนเริ่ม")
            return

        self.running = True
        self.log("[INFO] เริ่มระบบหลาย Thread แล้ว ✅")

        # สร้าง process สำหรับอ่านแชท
        self.process = multiprocessing.Process(target=self.chat_reader_process,
                                               args=(url, self.shared_queue))
        self.process.start()

        # สร้าง thread สำหรับประมวลผลเสียง
        threading.Thread(target=self.process_queue, daemon=True).start()

    def stop_system(self):
        self.running = False
        if self.process:
            self.process.terminate()
            self.process = None
        self.log("[INFO] หยุดระบบเรียบร้อยแล้ว")

    @staticmethod
    def chat_reader_process(url, shared_queue):
        import re
        def extract_video_id(u):
            match = re.search(r"v=([a-zA-Z0-9_-]{11})", u)
            return match.group(1) if match else u

        try:
            chat = pytchat.create(video_id=extract_video_id(url))
            while chat.is_alive():
                for c in chat.get().sync_items():
                    text = f"{c.author.name} พูดว่า: {c.message}"
                    shared_queue.put(text)
                time.sleep(1)
        except Exception as e:
            shared_queue.put(f"[ERROR_CHAT] {e}")

    def process_queue(self):
        while self.running:
            try:
                text = self.shared_queue.get(timeout=1)
                if text.startswith("[ERROR_CHAT]"):
                    self.log(f"[ข้อผิดพลาด] อ่านแชทล้มเหลว: {text.replace('[ERROR_CHAT]','').strip()}")
                    continue

                self.log(f"[แชท] {text}")
                delay = 30 if len(text) > 20 else 15
                self.log(f"[TTS] พูด: {text}")
                self.generate_tts(text)
                time.sleep(delay)
            except queue.Empty:
                continue

    def generate_tts(self, text):
        filename = os.path.join(self.temp_dir, f"tts_{int(time.time() * 1000)}.mp3")
        cmd = [sys.executable, "-m", "edge_tts",
               "--voice", self.voice,
               "--text", text,
               "--write-media", filename]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        except subprocess.CalledProcessError as e:
            self.log(f"[ERROR] edge-tts failed: {e.stderr.strip()}")
        except Exception as e:
            self.log(f"[ข้อผิดพลาด] สร้างเสียง: {e}")

    # ---------- Temp Cleaner ----------
    def clear_temp(self):
        count = 0
        for f in os.listdir(self.temp_dir):
            try:
                os.remove(os.path.join(self.temp_dir, f))
                count += 1
            except Exception:
                pass
        self.log(f"[🧹 ล้างไฟล์] ลบแล้ว {count} ไฟล์")


# ---------- Main ----------
if __name__ == "__main__":
    multiprocessing.freeze_support()  # ป้องกัน error บน Windows
    root = tk.Tk()
    app = YouTubeTTS(root)
    app.log("[ระบบ] พร้อมทำงานแล้ว ✅")
    root.mainloop()
