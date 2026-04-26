import os
import sys
import time
import queue
import threading
import subprocess
import tkinter as tk
from datetime import datetime
import configparser
import platform

import pytchat
from playsound3 import playsound

# ================= CONFIG =================
sys.stdout.reconfigure(encoding='utf-8')

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

try:
    YOUTUBE_VIDEO_ID = config.get("settings", "YOUTUBE_VIDEO_ID")
    VOICE = config.get("settings", "VOICE")
    DELAY_PER_CHAR = config.getfloat("settings", "DELAY_PER_CHAR")
    MAX_DELAY = config.getfloat("settings", "MAX_DELAY")
except Exception as e:
    print(f"❌ Error in config.ini: {e}")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

tts_queue: queue.Queue[str | None] = queue.Queue(maxsize=50)
running = True
IS_WINDOWS = platform.system() == "Windows"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- GUI ----------
def start_gui() -> None:
    root = tk.Tk()
    root.title("TTS Chat Bridge")
    root.geometry("300x100")

    if "--silent" in sys.argv:
        root.withdraw()

    label = tk.Label(root, text="🟢 TTS System Active\nCheck Console for logs", pady=20)
    label.pack()

    def on_close() -> None:
        global running
        running = False
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    def poll_running() -> None:
        if not running:
            on_close()
        else:
            root.after(500, poll_running)

    root.after(500, poll_running)
    root.mainloop()


# ---------- TTS WORKER ----------
def tts_worker() -> None:
    while True:
        try:
            text = tts_queue.get(timeout=1)
        except queue.Empty:
            if not running:
                break
            continue

        if text is None:
            tts_queue.task_done()
            break

        filename = os.path.join(CACHE_DIR, f"tts_{int(time.time() * 1000)}.mp3")

        cmd = [
            sys.executable,
            "-m", "edge_tts",
            "--voice", VOICE,
            "--text", text,
            "--write-media", filename,
        ]

        kwargs: dict = dict(capture_output=True, text=True)
        if IS_WINDOWS:
            kwargs["creationflags"] = 0x08000000

        try:
            result = subprocess.run(cmd, **kwargs)

            if result.returncode != 0:
                log(f"❌ edge_tts failed: {result.stderr.strip()}")
                continue

            if os.path.exists(filename):
                playsound(filename)
                try:
                    os.remove(filename)
                except OSError as e:
                    log(f"⚠️ Could not delete cache file: {e}")

            delay = min(MAX_DELAY, len(text) * DELAY_PER_CHAR)
            time.sleep(delay)

        except Exception as e:
            log(f"❌ TTS Error: {e}")

        finally:
            tts_queue.task_done()


# ---------- MAIN ----------
def main() -> None:
    global running

    log(f"🚀 Connecting to: {YOUTUBE_VIDEO_ID}")

    worker = threading.Thread(target=tts_worker, daemon=True, name="tts-worker")
    worker.start()

    gui_thread = threading.Thread(target=start_gui, daemon=True, name="gui")
    gui_thread.start()

    try:
        # ✅ Auto-reconnect loop — ถ้า pytchat หลุด จะ reconnect เองโดยไม่ต้องรอ watcher
        while running:
            try:
                log("🔌 Connecting to YouTube chat...")
                chat = pytchat.create(video_id=YOUTUBE_VIDEO_ID)

                if not chat.is_alive():
                    log("❌ ดึงแชทไม่ได้! เช็ก Video ID — retrying in 10s")
                    time.sleep(10)
                    continue

                log("✅ Connected! Listening to chat...")

                while running and chat.is_alive():
                    for c in chat.get().sync_items():
                        if not running:
                            break
                        msg = f"{c.author.name} พูดว่า {c.message}"
                        log(f"💬 {msg}")
                        try:
                            tts_queue.put_nowait(msg)
                        except queue.Full:
                            log("⚠️ TTS queue full, dropping message")

                    time.sleep(0.5)

                if running:
                    log("⚠️ Chat disconnected — reconnecting in 5s...")
                    time.sleep(5)

            except Exception as e:
                log(f"⚠️ Chat error: {e} — reconnecting in 5s")
                time.sleep(5)

    except KeyboardInterrupt:
        log("⛔ Stopping...")

    finally:
        running = False
        tts_queue.put(None)
        worker.join(timeout=5)
        log("✅ Shutdown complete")


# ---------- RUN ----------
if __name__ == "__main__":
    main()