import os
import sys
import time
import queue
import threading
import subprocess
import tkinter as tk
from datetime import datetime
import configparser
import re

import pytchat
from playsound3 import playsound

# ================= CONFIG =================
sys.stdout.reconfigure(encoding='utf-8')

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

try:
    YOUTUBE_VIDEO_ID = config.get("settings", "YOUTUBE_VIDEO_ID")
    # VOICE_PRIMARY = config.get("settings", "VOICE")  # เช่น th-TH-NiwatNeural
    DELAY_PER_CHAR = config.getfloat("settings", "DELAY_PER_CHAR")
    MAX_DELAY = config.getfloat("settings", "MAX_DELAY")
except Exception as e:
    print(f"❌ Error in config.ini: {e}")
    sys.exit()

# fallback voices (เรียงลำดับ)
VOICE_FALLBACKS = [
    "th-TH-PremwadeeNeural",
    "th-TH-NiwatNeural",
    "en-US-AriaNeural"
]

# ================= PATH =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

print("📁 CACHE_DIR =", CACHE_DIR)

tts_queue = queue.Queue()
running = True

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ---------- TEXT CLEAN ----------
def clean_text(text: str) -> str:
    text = re.sub(r"@\S+", "", text)  # ลบ @username
    text = re.sub(r"http\S+", "", text)  # ลบลิงก์
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200]  # จำกัดความยาว

# ---------- GUI ----------
def start_gui():
    root = tk.Tk()
    root.title("TTS Chat Bridge")
    root.geometry("300x100")

    if "--silent" in sys.argv:
        root.withdraw()

    label = tk.Label(root, text="🟢 TTS Active\nCheck console", pady=20)
    label.pack()

    def on_close():
        global running
        running = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

# ---------- EDGE TTS CALL ----------
def run_tts(text, voice, filename):
    cmd = [
        sys.executable,
        "-m", "edge_tts",
        "--voice", voice,
        "--text", text,
        "--write-media", filename
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=0x08000000
    )

    return result

# ---------- TTS WORKER ----------
def tts_worker():
    while running:
        try:
            text = tts_queue.get(timeout=1)
        except queue.Empty:
            continue

        if text is None:
            break

        text = clean_text(text)
        if not text:
            tts_queue.task_done()
            continue

        filename = os.path.join(CACHE_DIR, f"tts_{int(time.time()*1000)}.mp3")

        success = False

        for voice in VOICE_FALLBACKS:
            result = run_tts(text, voice, filename)

            if result.returncode == 0 and os.path.exists(filename):
                success = True
                break
            else:
                log(f"⚠️ voice {voice} failed")
                if result.stderr:
                    log(result.stderr.strip())

        if success:
            try:
                playsound(filename)
            except Exception as e:
                log(f"🔊 play error: {e}")
            finally:
                try:
                    os.remove(filename)
                except:
                    pass
        else:
            log("❌ ทุก voice ใช้ไม่ได้")

        time.sleep(min(MAX_DELAY, len(text) * DELAY_PER_CHAR))
        tts_queue.task_done()

# ---------- MAIN ----------
def main():
    global running

    log(f"🚀 Connecting to: {YOUTUBE_VIDEO_ID}")

    threading.Thread(target=tts_worker, daemon=True).start()
    threading.Thread(target=start_gui, daemon=True).start()

    try:
        chat = pytchat.create(video_id=YOUTUBE_VIDEO_ID)

        if not chat.is_alive():
            log("❌ ดึงแชทไม่ได้ (Video ID ผิดหรือสตรีมไม่เปิด)")
            return

        while running and chat.is_alive():
            for c in chat.get().sync_items():
                msg = f"{c.author.name} พูดว่า {c.message}"
                log(f"💬 {msg}")
                tts_queue.put(msg)

            time.sleep(0.5)

    except KeyboardInterrupt:
        log("⛔ Stopping...")

    finally:
        running = False
        tts_queue.put(None)

# ---------- RUN ----------
if __name__ == "__main__":
    main()