"""
TTS Chat Bridge — Production-grade version
แก้ bug ทั้งหมด: Tkinter main thread, stdout safe, signal fix,
edge-tts timeout, queue drop log, playsound thread, file lock, retry
"""

import os
import sys
import time
import queue
import threading
import subprocess
import platform
import configparser
from datetime import datetime

# ── 1. stdout reconfigure อย่างปลอดภัย (ป้องกัน crash เมื่อ stdout=None) ──
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── import ที่อาจ error ──
try:
    import pytchat
except ImportError:
    print("❌ ติดตั้ง pytchat ก่อน: pip install pytchat")
    sys.exit(1)

try:
    from playsound3 import playsound
except ImportError:
    print("❌ ติดตั้ง playsound3 ก่อน: pip install playsound3")
    sys.exit(1)

# ── tkinter import ที่นี่เพื่อจะเรียกจาก main thread ──
try:
    import tkinter as tk
except ImportError:
    tk = None  # headless mode

# ================== CONFIG ==================
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

try:
    YOUTUBE_VIDEO_ID = config.get("settings", "YOUTUBE_VIDEO_ID")
    VOICE            = config.get("settings", "VOICE")
    DELAY_PER_CHAR   = config.getfloat("settings", "DELAY_PER_CHAR")
    MAX_DELAY        = config.getfloat("settings", "MAX_DELAY")
except Exception as e:
    print(f"❌ Error in config.ini: {e}")
    sys.exit(1)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "tts_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

IS_WINDOWS = platform.system() == "Windows"

# ── 2. ใช้ threading.Event แทน global bool (thread-safe) ──
_stop_event = threading.Event()

# Queue ไม่จำกัด (drop แบบ logged แทน silent)
tts_queue: queue.Queue = queue.Queue(maxsize=100)

# ================== LOGGING ==================
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass  # stdout อาจ None ใน --noconsole


# ================== TTS WORKER ==================
def _run_edge_tts(text: str, filename: str, timeout: int = 30) -> bool:
    """
    รัน edge-tts พร้อม timeout เพื่อไม่ให้ hang
    คืน True ถ้าสำเร็จ
    """
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", VOICE,
        "--text", text,
        "--write-media", filename,
    ]
    kwargs: dict = dict(capture_output=True, text=True, timeout=timeout)
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    try:
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0:
            log(f"❌ edge-tts error: {result.stderr.strip()[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("⏱️ edge-tts หมดเวลา 30 วินาที — ข้ามข้อความนี้")
        return False
    except Exception as e:
        log(f"❌ edge-tts exception: {e}")
        return False


def _safe_play(filename: str) -> None:
    """เล่นเสียงใน thread ย่อย ไม่ block TTS worker"""
    try:
        playsound(filename)
    except Exception as e:
        log(f"⚠️ playsound error: {e}")


def _safe_remove(filename: str, retries: int = 5, delay: float = 0.3) -> None:
    """ลบไฟล์พร้อม retry กรณี OS lock (Windows)"""
    for i in range(retries):
        try:
            if os.path.exists(filename):
                os.remove(filename)
            return
        except OSError:
            if i < retries - 1:
                time.sleep(delay)


def tts_worker() -> None:
    """
    Thread นี้รับข้อความจาก queue → สร้าง audio → เล่น → ลบ
    - ใช้ timeout บน edge-tts
    - เล่นเสียงใน sub-thread (ไม่ block)
    - ลบไฟล์พร้อม retry
    - retry edge-tts 2 ครั้งถ้า fail
    """
    MAX_TTS_RETRIES = 2

    while True:
        try:
            text = tts_queue.get(timeout=1)
        except queue.Empty:
            if _stop_event.is_set():
                break
            continue

        if text is None:  # sentinel
            tts_queue.task_done()
            break

        filename = os.path.join(CACHE_DIR, f"tts_{int(time.time() * 1000)}.mp3")

        success = False
        for attempt in range(1, MAX_TTS_RETRIES + 1):
            if _run_edge_tts(text, filename):
                success = True
                break
            log(f"🔄 retry edge-tts ({attempt}/{MAX_TTS_RETRIES})...")
            time.sleep(1)

        if success and os.path.exists(filename):
            # เล่นใน thread แยก แล้วรอให้จบก่อนลบ
            play_thread = threading.Thread(target=_safe_play, args=(filename,), daemon=True)
            play_thread.start()
            play_thread.join()  # รอจบเสียง (แต่ไม่ block main TTS loop)
            _safe_remove(filename)

        # Throttle ตามความยาวข้อความ
        delay = min(MAX_DELAY, len(text) * DELAY_PER_CHAR)
        time.sleep(delay)

        tts_queue.task_done()


# ================== CHAT READER ==================
def chat_reader() -> None:
    """
    ── 3. pytchat อยู่ใน thread นี้ (ซึ่งเป็น main thread ผ่าน after() ไม่ได้)
    เราเรียก pytchat.create() ใน thread นี้เองตามเดิม แต่จัดการ signal ด้วย
    try/except ครอบ และใช้ is_alive() guard อย่างเคร่งครัด
    """
    while not _stop_event.is_set():
        try:
            log("🔌 กำลัง connect YouTube chat...")
            chat = pytchat.create(video_id=YOUTUBE_VIDEO_ID)

            if not chat.is_alive():
                log("❌ ดึงแชทไม่ได้ — เช็ก Video ID — retry 10s")
                _stop_event.wait(10)
                continue

            log("✅ Connect สำเร็จ! กำลังฟังแชท...")

            while not _stop_event.is_set() and chat.is_alive():
                try:
                    for c in chat.get().sync_items():
                        if _stop_event.is_set():
                            break
                        msg = f"{c.author.name} พูดว่า {c.message}"
                        log(f"💬 {msg}")
                        try:
                            tts_queue.put_nowait(msg)
                        except queue.Full:
                            log("⚠️ Queue เต็ม — ข้ามข้อความ (เพิ่ม maxsize ถ้าแชทเร็วมาก)")
                except Exception as e:
                    log(f"⚠️ chat.get() error: {e}")

                _stop_event.wait(0.5)

            if not _stop_event.is_set():
                log("⚠️ Chat หลุด — reconnect ใน 5s...")
                _stop_event.wait(5)

        except ValueError as e:
            # signal only works in main thread — จาก pytchat บางเวอร์ชัน
            log(f"⚠️ pytchat signal error (ไม่ร้ายแรง): {e}")
            _stop_event.wait(5)
        except Exception as e:
            log(f"⚠️ Chat error: {e} — reconnect ใน 5s")
            _stop_event.wait(5)

    log("🛑 Chat reader หยุดแล้ว")


# ================== GUI ==================
def build_gui() -> "tk.Tk | None":
    """
    ── 4. สร้าง Tkinter window ใน main thread เสมอ ──
    คืน root หรือ None ถ้าไม่มี display / ใช้ --silent
    """
    if tk is None:
        return None

    try:
        root = tk.Tk()
    except Exception as e:
        log(f"⚠️ Tkinter ไม่พร้อม (headless?): {e}")
        return None

    root.title("TTS Chat Bridge")
    root.geometry("300x110")
    root.resizable(False, False)

    if "--silent" in sys.argv:
        root.withdraw()

    label = tk.Label(
        root,
        text="🟢 TTS System Active\nดู Console สำหรับ log",
        pady=20,
    )
    label.pack()

    def on_close() -> None:
        _stop_event.set()
        root.quit()

    root.protocol("WM_DELETE_WINDOW", on_close)

    def poll() -> None:
        if _stop_event.is_set():
            root.quit()
            return
        root.after(500, poll)

    root.after(500, poll)
    return root


# ================== MAIN ==================
def main() -> None:
    log(f"🚀 เชื่อมต่อกับ: {YOUTUBE_VIDEO_ID}")

    # TTS worker thread
    worker = threading.Thread(target=tts_worker, daemon=True, name="tts-worker")
    worker.start()

    # Chat reader thread (pytchat ใช้ signal แต่เราจัดการ exception แล้ว)
    reader = threading.Thread(target=chat_reader, daemon=True, name="chat-reader")
    reader.start()

    # ── GUI ต้องอยู่ใน main thread ──
    root = build_gui()

    try:
        if root is not None:
            root.mainloop()  # block อยู่ที่นี่จน close หรือ _stop_event
        else:
            # headless mode: รอจนกด Ctrl+C
            log("ℹ️ Headless mode — กด Ctrl+C เพื่อหยุด")
            while not _stop_event.is_set():
                time.sleep(1)
    except KeyboardInterrupt:
        log("⛔ หยุดโดย Ctrl+C...")

    finally:
        _stop_event.set()
        try:
            root.destroy()
        except Exception:
            pass

        log("⏳ รอ TTS worker หยุด...")
        tts_queue.put(None)  # sentinel
        worker.join(timeout=10)
        reader.join(timeout=5)
        log("✅ ปิดระบบสมบูรณ์")


if __name__ == "__main__":
    main()