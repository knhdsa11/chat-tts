"""
TTS Chat Bridge — Production-grade
แก้ root cause: ไม่ใช้ pytchat (มี signal.signal ใน __init__)
ใช้ YouTube Live Chat API ผ่าน requests โดยตรงแทน
"""

import os
import sys
import re
import time
import json
import queue
import threading
import subprocess
import platform
import configparser
from datetime import datetime
import urllib.request
import urllib.error

# ── stdout safe reconfigure ──
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from playsound3 import playsound
except ImportError:
    print("❌ ติดตั้ง playsound3 ก่อน: pip install playsound3")
    sys.exit(1)

try:
    import tkinter as tk
    _HAS_TK = True
except ImportError:
    _HAS_TK = False

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
_stop_event = threading.Event()
tts_queue: queue.Queue = queue.Queue(maxsize=100)


# ================== LOGGING ==================
def log(msg: str) -> None:
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
    except Exception:
        pass


# ================== YOUTUBE CHAT (ไม่ใช้ pytchat) ==================
# ดึงจากหน้า /live_chat?is_popout=1&v=... ซึ่งมี ytInitialData ที่ถูกต้อง
# และใช้ continuation token จาก liveChatRenderer โดยตรง

_YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch_url(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers=_YT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log(f"❌ HTTP error ({url[:60]}): {e}")
        return None


def _get_live_chat_config(video_id: str) -> tuple[str | None, str | None, str | None]:
    """
    ดึง continuation token จากหน้า /live_chat (popout) ซึ่ง YouTube
    ใช้จริงสำหรับ get_live_chat API — token จากหน้า watch ใช้ไม่ได้
    คืน (continuation, api_key, client_version)
    """
    # ใช้หน้า live_chat embed — มี ytInitialData.contents.liveChatRenderer
    url = f"https://www.youtube.com/live_chat?is_popout=1&v={video_id}"
    html = _fetch_url(url)
    if not html:
        return None, None, None

    # --- ytInitialData JSON block ---
    m = re.search(r"ytInitialData\s*=\s*(\{.+?\});\s*(?:var |window\[|</script)", html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            # path: contents.liveChatRenderer.continuations[0].*.continuation
            lc = (
                data.get("contents", {})
                    .get("liveChatRenderer", {})
                    .get("continuations", [{}])[0]
            )
            continuation = (
                lc.get("invalidationContinuationData", {}).get("continuation")
                or lc.get("timedContinuationData", {}).get("continuation")
                or lc.get("reloadContinuationData", {}).get("continuation")
            )
        except (json.JSONDecodeError, IndexError, AttributeError):
            continuation = None
    else:
        continuation = None

    # fallback regex ถ้า JSON parse ไม่ได้
    if not continuation:
        for pat in [
            r'"invalidationContinuationData"\s*:\s*\{"continuation"\s*:\s*"([^"]+)"',
            r'"timedContinuationData"\s*:\s*\{"timeoutMs"[^}]*"continuation"\s*:\s*"([^"]+)"',
            r'"reloadContinuationData"\s*:\s*\{"continuation"\s*:\s*"([^"]+)"',
        ]:
            cm = re.search(pat, html)
            if cm:
                continuation = cm.group(1)
                break

    # --- INNERTUBE_API_KEY ---
    key_m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    api_key = key_m.group(1) if key_m else "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

    # --- INNERTUBE_CLIENT_VERSION ---
    ver_m = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
    client_ver = ver_m.group(1) if ver_m else "2.20240415.01.00"

    if not continuation:
        log("⚠️ ไม่พบ continuation token — stream อาจยังไม่ live หรือ Video ID ผิด")

    return continuation, api_key, client_ver


def _fetch_live_chat(
    continuation: str, api_key: str, client_ver: str
) -> tuple[list[str], str | None]:
    """
    POST ไปที่ get_live_chat endpoint พร้อม context ที่ครบถ้วน
    คืน ([messages], next_continuation_token)
    """
    url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}&prettyPrint=false"

    payload = json.dumps({
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_ver,
                "hl": "th",
                "gl": "TH",
                "userAgent": _YT_HEADERS["User-Agent"] + ",gzip(gfe)",
                "timeZone": "Asia/Bangkok",
                "utcOffsetMinutes": 420,
            }
        },
        "continuation": continuation,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            **_YT_HEADERS,
            "Content-Type": "application/json",
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/live_chat",
            "X-YouTube-Client-Name": "1",
            "X-YouTube-Client-Version": client_ver,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        log(f"❌ live_chat HTTP {e.code}: {body}")
        return [], None
    except Exception as e:
        log(f"❌ live_chat fetch error: {e}")
        return [], None

    messages: list[str] = []
    next_cont: str | None = None

    try:
        cr = data["continuationContents"]["liveChatContinuation"]

        # next continuation token
        for c in cr.get("continuations", []):
            tok = (
                c.get("invalidationContinuationData", {}).get("continuation")
                or c.get("timedContinuationData", {}).get("continuation")
                or c.get("reloadContinuationData", {}).get("continuation")
            )
            if tok:
                next_cont = tok
                break

        # parse messages
        for action in cr.get("actions", []):
            item = action.get("addChatItemAction", {}).get("item", {})
            renderer = (
                item.get("liveChatTextMessageRenderer")
                or item.get("liveChatPaidMessageRenderer")
            )
            if not renderer:
                continue

            author = renderer.get("authorName", {}).get("simpleText", "unknown")
            runs = renderer.get("message", {}).get("runs", [])
            text = "".join(
                r.get("text", "")
                or (r.get("emoji", {}).get("shortcuts") or [""])[0]
                for r in runs
            ).strip()

            if text:
                messages.append(f"{author} พูดว่า {text}")

    except (KeyError, TypeError):
        pass

    return messages, next_cont


def chat_reader() -> None:
    """
    YouTube Live Chat loop ด้วย HTTP ตรง
    ไม่มี signal ใดๆ — รันใน thread ย่อยได้ปกติ
    """
    while not _stop_event.is_set():
        log("🔌 กำลัง connect YouTube chat...")

        continuation, api_key, client_ver = _get_live_chat_config(YOUTUBE_VIDEO_ID)

        if not continuation:
            log("❌ ไม่พบ Live Chat — เช็ก Video ID หรือ stream ยังไม่เริ่ม — retry 15s")
            _stop_event.wait(15)
            continue

        log("✅ Connect สำเร็จ! กำลังฟังแชท...")
        consecutive_errors = 0

        while not _stop_event.is_set():
            messages, next_cont = _fetch_live_chat(continuation, api_key, client_ver)

            if next_cont:
                continuation = next_cont
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    log("⚠️ Chat หลุดหลายครั้ง — reconnect...")
                    break
                _stop_event.wait(3)
                continue

            for msg in messages:
                log(f"💬 {msg}")
                try:
                    tts_queue.put_nowait(msg)
                except queue.Full:
                    log("⚠️ Queue เต็ม — ข้ามข้อความ")

            # YouTube live chat อัปเดตทุก ~3-5 วินาที
            _stop_event.wait(3)

        if not _stop_event.is_set():
            log("⚠️ reconnect ใน 5s...")
            _stop_event.wait(5)

    log("🛑 Chat reader หยุดแล้ว")


# ================== TTS WORKER ==================
def _run_edge_tts(text: str, filename: str, timeout: int = 30) -> bool:
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", VOICE,
        "--text", text,
        "--write-media", filename,
    ]
    kwargs: dict = dict(capture_output=True, text=True, timeout=timeout)
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000

    try:
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0:
            log(f"❌ edge-tts error: {result.stderr.strip()[:200]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("⏱️ edge-tts timeout — ข้ามข้อความนี้")
        return False
    except Exception as e:
        log(f"❌ edge-tts exception: {e}")
        return False


def _safe_play(filename: str) -> None:
    try:
        playsound(filename)
    except Exception as e:
        log(f"⚠️ playsound error: {e}")


def _safe_remove(filename: str, retries: int = 5, delay: float = 0.3) -> None:
    for i in range(retries):
        try:
            if os.path.exists(filename):
                os.remove(filename)
            return
        except OSError:
            if i < retries - 1:
                time.sleep(delay)


def tts_worker() -> None:
    MAX_RETRIES = 2
    while True:
        try:
            text = tts_queue.get(timeout=1)
        except queue.Empty:
            if _stop_event.is_set():
                break
            continue

        if text is None:
            tts_queue.task_done()
            break

        filename = os.path.join(CACHE_DIR, f"tts_{int(time.time() * 1000)}.mp3")

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            if _run_edge_tts(text, filename):
                success = True
                break
            if attempt < MAX_RETRIES:
                log(f"🔄 retry edge-tts ({attempt}/{MAX_RETRIES})...")
                time.sleep(1)

        if success and os.path.exists(filename):
            play_t = threading.Thread(target=_safe_play, args=(filename,), daemon=True)
            play_t.start()
            play_t.join()
            _safe_remove(filename)

        delay = min(MAX_DELAY, len(text) * DELAY_PER_CHAR)
        time.sleep(delay)
        tts_queue.task_done()


# ================== GUI (main thread เท่านั้น) ==================
def build_gui():
    if not _HAS_TK:
        return None
    try:
        root = tk.Tk()
    except Exception as e:
        log(f"⚠️ Tkinter ไม่พร้อม: {e}")
        return None

    root.title("TTS Chat Bridge")
    root.geometry("300x110")
    root.resizable(False, False)

    if "--silent" in sys.argv:
        root.withdraw()

    tk.Label(root, text="🟢 TTS System Active\nดู Console สำหรับ log", pady=20).pack()

    def on_close():
        _stop_event.set()
        root.quit()

    root.protocol("WM_DELETE_WINDOW", on_close)

    def poll():
        if _stop_event.is_set():
            root.quit()
        else:
            root.after(500, poll)

    root.after(500, poll)
    return root


# ================== MAIN ==================
def main() -> None:
    log(f"🚀 เชื่อมต่อกับ: {YOUTUBE_VIDEO_ID}")

    worker = threading.Thread(target=tts_worker, daemon=True, name="tts-worker")
    worker.start()

    reader = threading.Thread(target=chat_reader, daemon=True, name="chat-reader")
    reader.start()

    # GUI ต้องอยู่ใน main thread เสมอ
    root = build_gui()

    try:
        if root is not None:
            root.mainloop()
        else:
            log("ℹ️ Headless mode — กด Ctrl+C เพื่อหยุด")
            while not _stop_event.is_set():
                time.sleep(1)
    except KeyboardInterrupt:
        log("⛔ หยุดโดย Ctrl+C...")
    finally:
        _stop_event.set()
        try:
            if root:
                root.destroy()
        except Exception:
            pass
        tts_queue.put(None)
        worker.join(timeout=10)
        reader.join(timeout=5)
        log("✅ ปิดระบบสมบูรณ์")


if __name__ == "__main__":
    main()