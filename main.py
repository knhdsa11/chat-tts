import os
import sys
import subprocess
import pygame
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import pytchat
import threading
import multiprocessing
import time
import queue
import shutil
from datetime import datetime, timedelta
import re
import json

# ---------------- Configuration Defaults ----------------
DEFAULT_VOICE = "th-TH-PremwadeeNeural"
TEMP_DIR = "tts_cache"
LOG_DIR = "logs"
PROFANITY_DEFAULT = ["fuck", "shit", "ควย", "สัส", "เหี้ย"]  # ตัวอย่างคำหยาบ -> สามารถปรับได้
SPAM_WINDOW_SECONDS = 10
SPAM_REPEAT_THRESHOLD = 3

# ---------------- Helpers ----------------
def safe_mkdir(p):
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass

safe_mkdir(TEMP_DIR)
safe_mkdir(LOG_DIR)

# ---------------- Main App ----------------
class YouTubeTTS:
    def __init__(self, root):
        # UI / state
        self.root = root
        self.root.title("YouTube Chat TTS — Advanced")
        self.root.geometry("900x700")
        self.root.configure(bg="#121212")

        # core state
        self.running = False
        self.chat_process = None
        self.manager = multiprocessing.Manager()
        self.ipc_queue = self.manager.Queue()  # process -> main thread
        self.tts_task_queue = queue.Queue()    # tasks for TTS worker (thread-safe)
        self.audio_worker_thread = None
        self.tts_worker_stop = threading.Event()

        # voice list
        self.voice = DEFAULT_VOICE
        self.available_voices = []
        self.load_voices()

        # delay settings
        self.delay_per_char = tk.DoubleVar(value=1.0)  # seconds per char
        self.min_delay = tk.IntVar(value=1)
        self.max_delay = tk.IntVar(value=15)

        # spam/filter settings
        self.spam_window = tk.IntVar(value=SPAM_WINDOW_SECONDS)
        self.spam_threshold = tk.IntVar(value=SPAM_REPEAT_THRESHOLD)
        self.profanity_list = set(PROFANITY_DEFAULT)

        # spam tracking: {(author, message): [timestamps]}
        self.recent_messages = {}

        # voice selection variable
        self.voice_var = tk.StringVar(value=self.voice)

        # log file buffer
        self.log_buffer = []

        # initialize pygame mixer
        pygame.mixer.init()

        # build UI
        self.setup_ui()

        # Start background thread to pull from IPC queue and enqueue TTS tasks
        threading.Thread(target=self.ipc_poster_thread, daemon=True).start()

    # ---------------- UI ----------------
    def setup_ui(self):
        header = tk.Label(self.root, text="🎧 YouTube Chat TTS — Advanced", font=("Segoe UI", 18, "bold"),
                          bg="#121212", fg="#00ffb3")
        header.pack(pady=8)

        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(top_frame, text="YouTube Live URL:").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.url_entry = ttk.Entry(top_frame, width=55)
        self.url_entry.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        self.start_btn = ttk.Button(top_frame, text="Start", command=self.start_system)
        self.start_btn.grid(row=0, column=2, padx=4)
        self.stop_btn = ttk.Button(top_frame, text="Stop", command=self.stop_system, state="disabled")
        self.stop_btn.grid(row=0, column=3, padx=4)
        ttk.Button(top_frame, text="Export Log", command=self.export_log).grid(row=0, column=4, padx=4)

        # voice selection + refresh voices
        voice_frame = ttk.Frame(self.root)
        voice_frame.pack(fill="x", padx=10, pady=4)
        ttk.Label(voice_frame, text="Voice:").grid(row=0, column=0, padx=4, sticky="w")
        self.voice_cb = ttk.Combobox(voice_frame, textvariable=self.voice_var, values=self.available_voices, width=50)
        self.voice_cb.grid(row=0, column=1, padx=4, sticky="w")
        ttk.Button(voice_frame, text="Refresh Voices", command=self.reload_voices).grid(row=0, column=2, padx=4)

        # Delay settings
        settings_frame = ttk.LabelFrame(self.root, text="Delay / Queue Settings")
        settings_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(settings_frame, text="Delay per char (s):").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.delay_per_char, width=8).grid(row=0, column=1, padx=6, pady=4, sticky="w")

        ttk.Label(settings_frame, text="Min delay (s):").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.min_delay, width=6).grid(row=0, column=3, padx=6, pady=4, sticky="w")

        ttk.Label(settings_frame, text="Max delay (s):").grid(row=0, column=4, padx=6, pady=4, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.max_delay, width=6).grid(row=0, column=5, padx=6, pady=4, sticky="w")

        # Spam / profanity settings
        filter_frame = ttk.LabelFrame(self.root, text="Spam & Profanity Filter")
        filter_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(filter_frame, text="Spam window (s):").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.spam_window, width=6).grid(row=0, column=1, padx=6, pady=4, sticky="w")

        ttk.Label(filter_frame, text="Repeat threshold:").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.spam_threshold, width=6).grid(row=0, column=3, padx=6, pady=4, sticky="w")

        ttk.Label(filter_frame, text="Add profanity / blacklist:").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self.black_entry = ttk.Entry(filter_frame, width=30)
        self.black_entry.grid(row=1, column=1, padx=6, pady=4, sticky="w")
        ttk.Button(filter_frame, text="Add", command=self.add_profanity).grid(row=1, column=2, padx=6)
        ttk.Button(filter_frame, text="Show List", command=self.show_profanity_list).grid(row=1, column=3, padx=6)

        # Log area
        self.log_box = scrolledtext.ScrolledText(self.root, width=110, height=24, bg="#1b1b1b", fg="#e6e6e6",
                                                 font=("Consolas", 10))
        self.log_box.pack(padx=10, pady=8)

        # Bottom controls
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill="x", padx=10, pady=6)
        ttk.Button(bottom_frame, text="Clear Temp", command=self.clear_temp).grid(row=0, column=0, padx=6)
        ttk.Button(bottom_frame, text="Clear Log", command=self.clear_log).grid(row=0, column=1, padx=6)

        # status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom_frame, textvariable=self.status_var).grid(row=0, column=2, padx=10, sticky="w")

        # bind voice dropdown selection
        self.voice_cb.bind("<<ComboboxSelected>>", lambda e: self.set_voice(self.voice_var.get()))

        # initial voice set
        self.set_voice(self.voice_var.get())

    # ---------------- Logging ----------------
    def log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        self.log_buffer.append(line)
        try:
            self.log_box.insert(tk.END, line + "\n")
            self.log_box.see(tk.END)
        except Exception:
            pass

    def export_log(self):
        if not self.log_buffer:
            messagebox.showinfo("Export Log", "ไม่มี log ให้ส่งออก")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".txt", initialdir=LOG_DIR,
                                                filetypes=[("Text files","*.txt"),("All files","*.*")],
                                                title="Save log as...")
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_buffer))
            messagebox.showinfo("Export Log", f"บันทึก log ที่: {filename}")
        except Exception as e:
            messagebox.showerror("Export Log", f"บันทึกไม่สำเร็จ: {e}")

    def clear_log(self):
        self.log_buffer = []
        try:
            self.log_box.delete("1.0", tk.END)
        except Exception:
            pass

    # ---------------- Voice handling ----------------
    def load_voices(self):
        """Try to load available voices using edge-tts list command."""
        voices = []
        try:
            # Attempt to call edge-tts to list voices
            # edge-tts supports: python -m edge_tts --list-voices
            cmd = [sys.executable, "-m", "edge_tts", "--list-voices"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            out = proc.stdout + "\n" + proc.stderr
            # Try to extract voice ids: common pattern like 'th-TH-PremwadeeNeural'
            ids = re.findall(r"[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural", out)
            # keep unique in order
            seen = set()
            for v in ids:
                if v not in seen:
                    seen.add(v)
                    voices.append(v)
        except Exception:
            # ignore, will fallback
            pass

        # fallback if none found
        if not voices:
            voices = [DEFAULT_VOICE, "en-US-AriaNeural", "en-US-GuyNeural"]

        self.available_voices = voices
        # update UI combobox if exists
        try:
            self.voice_var.set(voices[0])
        except Exception:
            pass

    def reload_voices(self):
        self.log("[INFO] กำลังโหลดรายชื่อเสียงจาก edge-tts...")
        self.load_voices()
        try:
            self.voice_cb.config(values=self.available_voices)
            self.voice_var.set(self.available_voices[0])
            self.set_voice(self.available_voices[0])
            self.log(f"[INFO] โหลดเสียงสำเร็จ: {len(self.available_voices)} เสียง")
        except Exception as e:
            self.log(f"[ERROR] โหลดเสียงไม่สำเร็จ: {e}")

    def set_voice(self, voice_id):
        self.voice = voice_id
        self.log(f"[INFO] ตั้งค่าเสียงเป็น: {voice_id}")

    # ---------------- Profanity / Spam ----------------
    def add_profanity(self):
        txt = self.black_entry.get().strip()
        if not txt:
            return
        # split by comma/space
        parts = re.split(r"[,;\s]+", txt)
        added = 0
        for p in parts:
            if p and p not in self.profanity_list:
                self.profanity_list.add(p.lower())
                added += 1
        self.black_entry.delete(0, tk.END)
        self.log(f"[FILTER] เพิ่มคำใน blacklist: {added} รายการ")

    def show_profanity_list(self):
        if not self.profanity_list:
            messagebox.showinfo("Profanity List", "ไม่มีคำในรายการ")
            return
        sorted_list = sorted(self.profanity_list)
        messagebox.showinfo("Profanity List", "\n".join(sorted_list))

    def check_profanity(self, text):
        txt = text.lower()
        for w in self.profanity_list:
            if w and w in txt:
                return True, w
        return False, None

    def check_spam(self, author, message):
        key = (author, message)
        now = datetime.now()
        window = timedelta(seconds=self.spam_window.get())
        # cleanup old timestamps for this key
        if key not in self.recent_messages:
            self.recent_messages[key] = []
        self.recent_messages[key] = [ts for ts in self.recent_messages[key] if now - ts <= window]
        self.recent_messages[key].append(now)
        count = len(self.recent_messages[key])
        if count >= max(1, self.spam_threshold.get()):
            return True, count
        return False, count

    # ---------------- IPC Poster ----------------
    def ipc_poster_thread(self):
        """Pull messages sent from chat_reader_process (ipc_queue) and push to local tts_task_queue
           This decouples the multiprocessing queue from local thread work and centralizes filtering.
        """
        while True:
            try:
                item = self.ipc_queue.get(timeout=1)
            except Exception:
                time.sleep(0.1)
                continue

            # item should be a dict: {"author":..., "message":...} or error string
            if isinstance(item, str) and item.startswith("[ERROR_CHAT]"):
                self.log(f"[ERROR_CHAT] {item.replace('[ERROR_CHAT]','').strip()}")
                continue

            if not isinstance(item, dict):
                # unknown format - just log
                self.log(f"[WARN] unknown ipc item: {item}")
                continue

            author = item.get("author", "Unknown")
            message = item.get("message", "")

            # check profanity
            prof, word = self.check_profanity(message)
            if prof:
                self.log(f"[FILTER] พบคำต้องห้าม ('{word}') จาก {author} -> บล็อกข้อความ")
                continue

            # check spam
            is_spam, count = self.check_spam(author, message)
            if is_spam:
                self.log(f"[FILTER] บล็อก spam: ข้อความซ้ำจาก {author} จำนวน {count} ครั้ง")
                continue

            # enqueue the TTS task (author separate)
            tts_text = f"{author} พูดว่า: {message}"
            self.log(f"[QUEUE] เพิ่มงาน TTS ของ {author}: \"{message[:60]}{'...' if len(message)>60 else ''}\"")
            self.tts_task_queue.put({"author": author, "message": message, "tts_text": tts_text})

    # ---------------- Start / Stop ----------------
    def start_system(self):
        if self.running:
            messagebox.showinfo("Already running", "ระบบกำลังทำงานอยู่")
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "กรุณาใส่ลิงก์ YouTube Live")
            return

        # ensure voice value from dropdown
        if self.voice_var.get():
            self.set_voice(self.voice_var.get())

        self.running = True
        self.status_var.set("Starting...")
        self.log("[INFO] เริ่มระบบอ่านแชท (process) และคิวเสียง")

        # start chat reader process
        self.chat_process = multiprocessing.Process(target=self.chat_reader_process, args=(url, self.ipc_queue))
        self.chat_process.start()

        # start audio worker thread
        self.tts_worker_stop.clear()
        self.audio_worker_thread = threading.Thread(target=self.tts_worker, daemon=True)
        self.audio_worker_thread.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Running")

    def stop_system(self):
        if not self.running:
            return
        self.running = False
        self.status_var.set("Stopping...")
        self.log("[INFO] กำลังหยุดระบบ...")

        try:
            if self.chat_process and self.chat_process.is_alive():
                self.chat_process.terminate()
                self.chat_process.join(timeout=2)
        except Exception:
            pass
        self.chat_process = None

        # signal tts worker to stop after finishing queued tasks or immediately
        self.tts_worker_stop.set()
        # clear tts_task_queue if any left (optional: we clear to stop immediately)
        try:
            while not self.tts_task_queue.empty():
                self.tts_task_queue.get_nowait()
        except Exception:
            pass

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Stopped")
        self.log("[INFO] ระบบหยุดเรียบร้อยแล้ว")

    # ---------------- Chat Reader Process (worker) ----------------
    @staticmethod
    def chat_reader_process(url, ipc_queue):
        """
        Runs in separate process. Posts dicts into ipc_queue:
        {"author": name, "message": message}
        On error, posts string: "[ERROR_CHAT] error message"
        """
        import re
        try:
            def extract_video_id(u):
                # try to extract v= and also short urls
                m = re.search(r"v=([a-zA-Z0-9_-]{11})", u)
                if m:
                    return m.group(1)
                # youtu.be/VIDEO
                m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", u)
                if m:
                    return m.group(1)
                # fallback: return u
                return u

            video_id = extract_video_id(url)
            chat = pytchat.create(video_id=video_id)
            while chat.is_alive():
                try:
                    for c in chat.get().sync_items():
                        ipc_queue.put({"author": c.author.name, "message": c.message})
                    time.sleep(0.5)
                except Exception as e:
                    ipc_queue.put(f"[ERROR_CHAT] {e}")
                    time.sleep(1)
        except Exception as e:
            ipc_queue.put(f"[ERROR_CHAT] {e}")

    # ---------------- TTS Worker ----------------
    def tts_worker(self):
        """
        Runs in a thread. Pulls tasks from self.tts_task_queue sequentially,
        converts to tts file using edge-tts, plays using pygame, respects delay per char and min/max caps.
        """
        self.log("[TTS_WORKER] เริ่มทำงาน")
        while not self.tts_worker_stop.is_set():
            try:
                task = self.tts_task_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Build speak text with author separated
            tts_text = task.get("tts_text") or f"{task.get('author')} พูดว่า: {task.get('message')}"
            # Compute delay
            try:
                per_char = float(self.delay_per_char.get())
            except Exception:
                per_char = 1.0
            raw_delay = len(tts_text) * per_char
            delay = int(max(self.min_delay.get(), min(self.max_delay.get(), raw_delay)))
            # generate tts file and play
            try:
                filename = os.path.join(TEMP_DIR, f"tts_{int(time.time()*1000)}.mp3")
                cmd = [
                    sys.executable, "-m", "edge_tts",
                    "--voice", self.voice,
                    "--text", tts_text,
                    "--write-media", filename
                ]
                self.log(f"[TTS] สร้างไฟล์เสียง: {filename} ({len(tts_text)} chars, delay={delay}s)")
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.log(f"[ERROR] edge-tts failed: {proc.stderr.strip() or proc.stdout.strip()}")
                    # small backoff then continue
                    time.sleep(0.5)
                    continue

                # play file synchronously
                try:
                    pygame.mixer.music.load(filename)
                    pygame.mixer.music.play()
                    # while playing, also allow stop event to interrupt if app stopping
                    while pygame.mixer.music.get_busy():
                        if self.tts_worker_stop.is_set():
                            pygame.mixer.music.stop()
                            break
                        time.sleep(0.05)
                except Exception as e:
                    self.log(f"[ERROR] เล่นไฟล์เสียงล้มเหลว: {e}")

                # after playing wait for delay (but allow interruption)
                self.log(f"[TTS] รอหลังเล่น: {delay} วินาที")
                waited = 0.0
                while waited < delay:
                    if self.tts_worker_stop.is_set():
                        break
                    time.sleep(0.2)
                    waited += 0.2

                # optional: cleanup older files if many
                self.cleanup_old_tts_files(max_files=50)

            except Exception as e:
                self.log(f"[ERROR] ใน TTS worker: {e}")
                time.sleep(0.5)

        self.log("[TTS_WORKER] หยุดทำงาน")

    def cleanup_old_tts_files(self, max_files=50):
        try:
            files = sorted([os.path.join(TEMP_DIR, f) for f in os.listdir(TEMP_DIR)], key=os.path.getmtime, reverse=True)
            # keep newest max_files
            for f in files[max_files:]:
                try:
                    os.remove(f)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------------- Utilities ----------------
    def clear_temp(self):
        count = 0
        try:
            for f in os.listdir(TEMP_DIR):
                fp = os.path.join(TEMP_DIR, f)
                try:
                    os.remove(fp)
                    count += 1
                except Exception:
                    pass
            self.log(f"[CLEAN] ลบไฟล์ temp: {count} ไฟล์")
        except Exception as e:
            self.log(f"[ERROR] ล้าง temp ล้มเหลว: {e}")

# ---------------- Main entry ----------------
if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows support
    root = tk.Tk()
    app = YouTubeTTS(root)
    app.log("[SYSTEM] พร้อมทำงาน ✅")
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_system(), root.destroy()))
    root.mainloop()