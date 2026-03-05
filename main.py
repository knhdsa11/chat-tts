import os
import sys
import time
import queue
import threading
import subprocess
import shutil
import tkinter as tk
from datetime import datetime
import configparser

import pytchat
from playsound3 import playsound

# ================= CONFIG =================
config = configparser.ConfigParser()
config.read("config.ini")

YOUTUBE_VIDEO_ID = config.get("settings","YOUTUBE_VIDEO_ID") # ใส่ Video ID หรือ URL ไลฟ์
print(YOUTUBE_VIDEO_ID)   
VOICE = config.get("settings","VOICE")

CACHE_DIR = "tts_cache"
DELAY_PER_CHAR = config.getfloat("settings","DELAY_PER_CHAR")
MAX_DELAY = config.getfloat("settings","MAX_DELAY")
CLEAR_EVERY = config.getint("settings","CLEAR_EVERY")
# ==========================================

os.makedirs(CACHE_DIR, exist_ok=True)

tts_queue = queue.Queue()
played_count = 0
running = True


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ---------- GUI (ว่าง ๆ สำหรับ OBS) ----------
def start_gui():
    root = tk.Tk()
    root.title("TTS Audio Bridge")
    root.geometry("320x120")
    root.resizable(False, False)

    label = tk.Label(
        root,
        text="🎧 TTS Audio Running\nใช้หน้าต่างนี้จับเสียงเข้า OBS",
        font=("Segoe UI", 10)
    )
    label.pack(expand=True)

    # ปิด GUI = ปิดโปรแกรมทั้งหมด
    def on_close():
        global running
        running = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


# ---------- TTS WORKER ----------
def tts_worker():
    global played_count

    while running:
        try:
            text = tts_queue.get(timeout=1)
        except queue.Empty:
            continue

        if text is None:
            break

        filename = os.path.join(
            CACHE_DIR, f"tts_{int(time.time() * 1000)}.mp3"
        )

        cmd = [
            sys.executable, "-m", "edge_tts",
            "--voice", VOICE,
            "--text", text,
            "--write-media", filename
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            playsound(filename)

            played_count += 1
            if played_count % CLEAR_EVERY == 0:
                clear_cache()

            delay = min(MAX_DELAY, len(text) * DELAY_PER_CHAR)
            time.sleep(delay)

        except Exception as e:
            log(f"❌ TTS ERROR: {e}")

        tts_queue.task_done()


def clear_cache():
    try:
        shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR, exist_ok=True)
        log("🧹 ล้าง tts_cache แล้ว")
    except Exception:
        pass


# ---------- MAIN (pytchat ต้องอยู่ main thread) ----------
def main():
    global running
    log("🎤 TTS CMD RUNNING (Ctrl+C เพื่อหยุด)")

    # เริ่ม worker
    worker = threading.Thread(target=tts_worker, daemon=True)
    worker.start()

    # เริ่ม GUI (thread แยก)
    gui_thread = threading.Thread(target=start_gui, daemon=True)
    gui_thread.start()

    # pytchat ต้องอยู่ main thread
    chat = pytchat.create(video_id=YOUTUBE_VIDEO_ID)

    try:
        while running and chat.is_alive():
            for c in chat.get().sync_items():
                msg = f"{c.author.name} พูดว่า {c.message}"
                log(f"💬 {msg}")
                tts_queue.put(msg)

            time.sleep(1)

    except KeyboardInterrupt:
        log("⛔ หยุดระบบ")

    finally:
        running = False
        tts_queue.put(None)
        worker.join()


if __name__ == "__main__":
    main()