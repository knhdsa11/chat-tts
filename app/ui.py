import os
import queue
import threading
import time
import multiprocessing
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk, scrolledtext, messagebox, filedialog

from app.config import (
    DEFAULT_VOICE,
    LOG_DIR,
    MAX_RECENT_MESSAGE_KEYS,
    MAX_TTS_CACHE_FILES,
    PROFANITY_DEFAULT,
    SPAM_REPEAT_THRESHOLD,
    SPAM_WINDOW_SECONDS,
    TEMP_DIR,
)
from app.services import (
    chat_reader_process,
    cleanup_old_tts_files,
    generate_tts_file,
    load_voices,
    play_audio_non_blocking,
    prune_recent_messages,
)
from app.utils import DelayConfig


class YouTubeTTSApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("YouTube Chat TTS — v3 (modular)")
        self.root.geometry("940x760")
        self.root.configure(bg="#121212")

        self.running = False
        self.chat_process: multiprocessing.Process | None = None
        self.manager = multiprocessing.Manager()
        self.ipc_queue = self.manager.Queue()
        self.tts_task_queue: queue.Queue[dict] = queue.Queue()
        self.audio_worker_thread: threading.Thread | None = None
        self.tts_worker_stop = threading.Event()

        self.voice = DEFAULT_VOICE
        self.available_voices: list[str] = []
        self.voice_var = tk.StringVar(value=self.voice)

        self.delay_per_char = tk.DoubleVar(value=0.12)
        self.min_delay = tk.IntVar(value=1)
        self.max_delay = tk.IntVar(value=10)

        self.spam_window = tk.IntVar(value=SPAM_WINDOW_SECONDS)
        self.spam_threshold = tk.IntVar(value=SPAM_REPEAT_THRESHOLD)
        self.profanity_list = set(w.lower() for w in PROFANITY_DEFAULT)
        self.recent_messages: dict[tuple[str, str], list[datetime]] = {}

        self.log_buffer: list[str] = []

        self.setup_ui()
        self.reload_voices(silent=True)
        self.bind_validators()
        threading.Thread(target=self.ipc_poster_thread, daemon=True).start()

    def setup_ui(self) -> None:
        header = tk.Label(
            self.root,
            text="🎧 YouTube Chat TTS — v3",
            font=("Segoe UI", 18, "bold"),
            bg="#121212",
            fg="#00ffb3",
        )
        header.pack(pady=8)

        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(top_frame, text="YouTube Live URL:").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.url_entry = ttk.Entry(top_frame, width=65)
        self.url_entry.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        self.start_btn = ttk.Button(top_frame, text="Start", command=self.start_system)
        self.start_btn.grid(row=0, column=2, padx=4)
        self.stop_btn = ttk.Button(top_frame, text="Stop", command=self.stop_system, state="disabled")
        self.stop_btn.grid(row=0, column=3, padx=4)
        ttk.Button(top_frame, text="Export Log", command=self.export_log).grid(row=0, column=4, padx=4)

        voice_frame = ttk.Frame(self.root)
        voice_frame.pack(fill="x", padx=10, pady=4)
        ttk.Label(voice_frame, text="Voice:").grid(row=0, column=0, padx=4, sticky="w")
        self.voice_cb = ttk.Combobox(voice_frame, textvariable=self.voice_var, values=self.available_voices, width=52)
        self.voice_cb.grid(row=0, column=1, padx=4, sticky="w")
        ttk.Button(voice_frame, text="Refresh Voices", command=self.reload_voices).grid(row=0, column=2, padx=4)

        settings_frame = ttk.LabelFrame(self.root, text="Delay / Queue Settings")
        settings_frame.pack(fill="x", padx=10, pady=6)
        ttk.Label(settings_frame, text="Delay per char (s):").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.delay_per_char_entry = ttk.Entry(settings_frame, textvariable=self.delay_per_char, width=8)
        self.delay_per_char_entry.grid(row=0, column=1, padx=6, pady=4, sticky="w")
        ttk.Label(settings_frame, text="Min delay (s):").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.min_delay_entry = ttk.Entry(settings_frame, textvariable=self.min_delay, width=6)
        self.min_delay_entry.grid(row=0, column=3, padx=6, pady=4, sticky="w")
        ttk.Label(settings_frame, text="Max delay (s):").grid(row=0, column=4, padx=6, pady=4, sticky="w")
        self.max_delay_entry = ttk.Entry(settings_frame, textvariable=self.max_delay, width=6)
        self.max_delay_entry.grid(row=0, column=5, padx=6, pady=4, sticky="w")

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

        self.log_box = scrolledtext.ScrolledText(
            self.root,
            width=115,
            height=25,
            bg="#1b1b1b",
            fg="#e6e6e6",
            font=("Consolas", 10),
        )
        self.log_box.pack(padx=10, pady=8)

        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill="x", padx=10, pady=6)
        ttk.Button(bottom_frame, text="Clear Temp", command=self.clear_temp).grid(row=0, column=0, padx=6)
        ttk.Button(bottom_frame, text="Clear Log", command=self.clear_log).grid(row=0, column=1, padx=6)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom_frame, textvariable=self.status_var).grid(row=0, column=2, padx=10, sticky="w")

        self.voice_cb.bind("<<ComboboxSelected>>", lambda _: self.set_voice(self.voice_var.get()))

    def bind_validators(self) -> None:
        self.delay_per_char_entry.bind("<FocusOut>", lambda _: self.validate_delays())
        self.min_delay_entry.bind("<FocusOut>", lambda _: self.validate_delays())
        self.max_delay_entry.bind("<FocusOut>", lambda _: self.validate_delays())

    def validate_delays(self) -> DelayConfig:
        try:
            cfg = DelayConfig(
                per_char=float(self.delay_per_char.get()),
                minimum=int(self.min_delay.get()),
                maximum=int(self.max_delay.get()),
            ).normalized()
        except (tk.TclError, ValueError):
            cfg = DelayConfig(per_char=0.12, minimum=1, maximum=10)

        self.delay_per_char.set(cfg.per_char)
        self.min_delay.set(cfg.minimum)
        self.max_delay.set(cfg.maximum)
        return cfg

    def log(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        self.log_buffer.append(line)
        self.log_box.insert(tk.END, line + "\n")
        self.log_box.see(tk.END)

    def reload_voices(self, silent: bool = False) -> None:
        if not silent:
            self.log("[INFO] กำลังโหลดรายชื่อเสียงจาก edge-tts...")
        self.available_voices = load_voices()
        self.voice_cb.config(values=self.available_voices)
        self.voice_var.set(self.available_voices[0])
        self.set_voice(self.available_voices[0])
        if not silent:
            self.log(f"[INFO] โหลดเสียงสำเร็จ: {len(self.available_voices)} เสียง")

    def set_voice(self, voice_id: str) -> None:
        self.voice = voice_id.strip() or DEFAULT_VOICE
        self.log(f"[INFO] ตั้งค่าเสียงเป็น: {self.voice}")

    def add_profanity(self) -> None:
        txt = self.black_entry.get().strip()
        if not txt:
            return
        parts = txt.replace(";", " ").replace(",", " ").split()
        added = 0
        for part in parts:
            token = part.strip().lower()
            if token and token not in self.profanity_list:
                self.profanity_list.add(token)
                added += 1
        self.black_entry.delete(0, tk.END)
        self.log(f"[FILTER] เพิ่มคำใน blacklist: {added} รายการ")

    def show_profanity_list(self) -> None:
        if not self.profanity_list:
            messagebox.showinfo("Profanity List", "ไม่มีคำในรายการ")
            return
        messagebox.showinfo("Profanity List", "\n".join(sorted(self.profanity_list)))

    def check_profanity(self, text: str) -> tuple[bool, str | None]:
        txt = text.lower()
        for word in self.profanity_list:
            if word in txt:
                return True, word
        return False, None

    def check_spam(self, author: str, message: str) -> tuple[bool, int]:
        key = (author, message)
        now = datetime.now()
        window = timedelta(seconds=max(1, self.spam_window.get()))

        if key not in self.recent_messages:
            self.recent_messages[key] = []
        self.recent_messages[key] = [ts for ts in self.recent_messages[key] if now - ts <= window]
        self.recent_messages[key].append(now)
        prune_recent_messages(self.recent_messages, MAX_RECENT_MESSAGE_KEYS)

        count = len(self.recent_messages[key])
        return count >= max(1, self.spam_threshold.get()), count

    def ipc_poster_thread(self) -> None:
        while True:
            try:
                item = self.ipc_queue.get(timeout=1)
            except queue.Empty:
                continue

            if isinstance(item, str) and item.startswith("[ERROR_CHAT]"):
                self.log(f"[ERROR_CHAT] {item.replace('[ERROR_CHAT]', '').strip()}")
                continue

            if not isinstance(item, dict):
                self.log(f"[WARN] unknown ipc item: {item}")
                continue

            author = item.get("author", "Unknown")
            message = item.get("message", "")

            prof, word = self.check_profanity(message)
            if prof:
                self.log(f"[FILTER] พบคำต้องห้าม ('{word}') จาก {author} -> บล็อก")
                continue

            is_spam, count = self.check_spam(author, message)
            if is_spam:
                self.log(f"[FILTER] บล็อก spam: ข้อความซ้ำจาก {author} ({count} ครั้ง)")
                continue

            self.tts_task_queue.put({"author": author, "message": message, "tts_text": f"{author} พูดว่า: {message}"})

    def start_system(self) -> None:
        if self.running:
            messagebox.showinfo("Already running", "ระบบกำลังทำงานอยู่")
            return

        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "กรุณาใส่ลิงก์ YouTube Live")
            return

        self.validate_delays()
        self.running = True
        self.status_var.set("Starting...")

        self.chat_process = multiprocessing.Process(target=chat_reader_process, args=(url, self.ipc_queue))
        self.chat_process.start()

        self.tts_worker_stop.clear()
        self.audio_worker_thread = threading.Thread(target=self.tts_worker, daemon=True)
        self.audio_worker_thread.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Running")
        self.log("[INFO] เริ่มระบบ...")

    def stop_system(self) -> None:
        if not self.running:
            return

        self.running = False
        self.status_var.set("Stopping...")
        self.tts_worker_stop.set()

        if self.chat_process and self.chat_process.is_alive():
            self.chat_process.terminate()
            self.chat_process.join(timeout=3)
        self.chat_process = None

        while not self.tts_task_queue.empty():
            try:
                self.tts_task_queue.get_nowait()
            except queue.Empty:
                break

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Stopped")
        self.log("[INFO] ระบบหยุดเรียบร้อย")

    def tts_worker(self) -> None:
        self.log("[TTS_WORKER] เริ่มทำงาน")
        while not self.tts_worker_stop.is_set():
            try:
                task = self.tts_task_queue.get(timeout=0.6)
            except queue.Empty:
                continue

            cfg = self.validate_delays()
            text = task.get("tts_text", "")
            raw_delay = len(text) * cfg.per_char
            delay = int(max(cfg.minimum, min(cfg.maximum, raw_delay)))

            ok, filename, err = generate_tts_file(text, self.voice, TEMP_DIR)
            if not ok:
                self.log(f"[ERROR] edge-tts failed: {err}")
                continue

            play_audio_non_blocking(filename, self.tts_worker_stop, self.log)

            waited = 0.0
            while waited < delay and not self.tts_worker_stop.is_set():
                time.sleep(0.2)
                waited += 0.2

            cleanup_old_tts_files(TEMP_DIR, MAX_TTS_CACHE_FILES, self.log)

        self.log("[TTS_WORKER] หยุดทำงาน")

    def export_log(self) -> None:
        if not self.log_buffer:
            messagebox.showinfo("Export Log", "ไม่มี log ให้ส่งออก")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialdir=LOG_DIR,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not filename:
            return
        with open(filename, "w", encoding="utf-8") as file:
            file.write("\n".join(self.log_buffer))
        messagebox.showinfo("Export Log", f"บันทึก log ที่: {filename}")

    def clear_log(self) -> None:
        self.log_buffer = []
        self.log_box.delete("1.0", tk.END)

    def clear_temp(self) -> None:
        removed = 0
        for name in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, name)
            try:
                os.remove(file_path)
                removed += 1
            except OSError as exc:
                self.log(f"[WARN] ลบไฟล์ไม่สำเร็จ: {file_path} ({exc})")
        self.log(f"[CLEAN] ลบไฟล์ temp: {removed} ไฟล์")
