import subprocess
import time
import sys
import os
from datetime import datetime

TARGET_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

POLL_INTERVAL   = 5   # วินาที — ตรวจสอบทุกกี่วินาที
RESTART_DELAY   = 2   # วินาที — รอก่อน restart
CRASH_THRESHOLD = 5   # crash กี่ครั้งใน window ถึงจะ backoff
CRASH_WINDOW    = 60  # วินาที — นับ crash ย้อนหลังกี่วินาที
BACKOFF_DELAY   = 30  # วินาที — รอนานขึ้นเมื่อ crash ถี่เกินไป


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_target() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, TARGET_SCRIPT],
        creationflags=0x08000000 if os.name == "nt" else 0,
    )


def monitor() -> None:
    log(f"🛡️  Watcher active — monitoring {os.path.basename(TARGET_SCRIPT)}")

    process = run_target()
    restart_times: list[float] = []

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            code = process.poll()

            if code is None:
                continue

            if code == 0:
                log("✅ Main script exited cleanly (code 0). Watcher shutting down.")
                break

            log(f"⚠️  Main script stopped (exit code {code}).")

            now = time.monotonic()
            restart_times = [t for t in restart_times if now - t < CRASH_WINDOW]

            if len(restart_times) >= CRASH_THRESHOLD:
                log(
                    f"🔴 {CRASH_THRESHOLD} crashes in {CRASH_WINDOW}s — "
                    f"backing off for {BACKOFF_DELAY}s..."
                )
                time.sleep(BACKOFF_DELAY)
                restart_times.clear()
            else:
                time.sleep(RESTART_DELAY)

            restart_times.append(time.monotonic())
            log("🔄 Restarting...")
            process = run_target()

    except KeyboardInterrupt:
        log("\n⛔ Watcher interrupted.")

    finally:
        if process is not None and process.poll() is None:
            log("🧹 Terminating child process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("⚡ Force-killing unresponsive process.")
                process.kill()
        log("👋 Watcher stopped.")


if __name__ == "__main__":
    monitor()