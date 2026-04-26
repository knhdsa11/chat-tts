"""
gui.py — TTS Chat Bridge Dashboard
รัน main.py เป็น subprocess แล้ว pipe stdout มาแสดงใน GUI
ไม่แตะ logic ใน main.py เลย
"""

import os
import sys
import time
import subprocess
import threading
import queue
import configparser
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime

# ── stdout safe ──
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────── paths ────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MAIN_PY    = os.path.join(BASE_DIR, "api.py")
CONFIG_INI = os.path.join(BASE_DIR, "config.ini")

# ─────────────────────────── config ───────────────────────────
_cfg = configparser.ConfigParser()
_cfg.read(CONFIG_INI, encoding="utf-8")

def _cfg_get(key: str, fallback: str = "") -> str:
    try:
        return _cfg.get("settings", key)
    except Exception:
        return fallback

def _cfg_set(key: str, value: str) -> None:
    if not _cfg.has_section("settings"):
        _cfg.add_section("settings")
    _cfg.set("settings", key, value)
    with open(CONFIG_INI, "w", encoding="utf-8") as f:
        _cfg.write(f)

# ─────────────────────────── watcher settings ─────────────────
RESTART_DELAY   = 2   # วินาที — รอก่อน restart
CRASH_THRESHOLD = 5   # crash กี่ครั้งใน window ถึง backoff
CRASH_WINDOW    = 60  # วินาที — นับ crash ย้อนหลังกี่วินาที
BACKOFF_DELAY   = 30  # วินาที — รอนานขึ้นเมื่อ crash ถี่

# ─────────────────────────── palette ──────────────────────────
BG        = "#0f1117"
BG2       = "#181c27"
BG3       = "#1e2333"
BORDER    = "#2a3050"
RED       = "#ff4f4f"
GREEN     = "#23d18b"
YELLOW    = "#f5c542"
BLUE      = "#5b9cf6"
MUTED     = "#6b7280"
TEXT      = "#e8eaf0"
TEXT2     = "#a0aec0"
ACCENT    = "#5b9cf6"

# ─────────────────────────── log colors ───────────────────────
LOG_TAGS = {
    "✅": GREEN,
    "🚀": BLUE,
    "🔌": BLUE,
    "💬": TEXT,
    "⚠️": YELLOW,
    "❌": RED,
    "⏱️": YELLOW,
    "🔄": YELLOW,
    "🛑": RED,
    "⛔": RED,
    "ℹ️": MUTED,
    "⏳": MUTED,
}

def _tag_color(line: str) -> str:
    for icon, color in LOG_TAGS.items():
        if icon in line:
            return color
    return TEXT2


# ══════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TTS Chat Bridge")
        self.geometry("780x540")
        self.minsize(640, 420)
        self.configure(bg=BG)
        self.resizable(True, True)

        # process handle
        self._proc: subprocess.Popen | None = None
        self._running = False
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._msg_count = 0
        self._restart_count = 0
        self._crash_times: list[float] = []   # monotonic timestamps
        self._start_time: float | None = None

        self._build_fonts()
        self._build_ui()
        self._poll_logs()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────── fonts ──────────────────────────────────
    def _build_fonts(self):
        self.fn_title  = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.fn_mono   = tkfont.Font(family="Consolas", size=9)
        self.fn_label  = tkfont.Font(family="Segoe UI", size=9)
        self.fn_btn    = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.fn_stat   = tkfont.Font(family="Consolas", size=14, weight="bold")
        self.fn_small  = tkfont.Font(family="Segoe UI", size=8)

    # ──────────────── UI ─────────────────────────────────────
    def _build_ui(self):
        # ── top bar ──
        top = tk.Frame(self, bg=BG, pady=8)
        top.pack(fill="x", padx=16)

        dot_frame = tk.Frame(top, bg=BG)
        dot_frame.pack(side="left")
        self._status_dot = tk.Label(
            dot_frame, text="●", fg=MUTED, bg=BG,
            font=tkfont.Font(family="Segoe UI", size=18),
        )
        self._status_dot.pack(side="left")
        tk.Label(dot_frame, text=" TTS Chat Bridge", fg=TEXT, bg=BG,
                 font=self.fn_title).pack(side="left")

        # uptime
        self._uptime_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._uptime_var,
                 fg=MUTED, bg=BG, font=self.fn_small).pack(side="right", padx=4)

        # ── stats row ──
        stats = tk.Frame(self, bg=BG2, pady=10)
        stats.pack(fill="x", padx=16, pady=(0, 8))
        self._stat_frames = {}
        for col, (key, label, val) in enumerate([
            ("msgs",     "Messages", "0"),
            ("restarts", "Restarts", "0"),
            ("status",   "Status",   "idle"),
        ]):
            f = tk.Frame(stats, bg=BG2)
            f.pack(side="left", expand=True, fill="x")
            vv = tk.StringVar(value=val)
            tk.Label(f, textvariable=vv, fg=ACCENT, bg=BG2,
                     font=self.fn_stat).pack()
            tk.Label(f, text=label, fg=MUTED, bg=BG2,
                     font=self.fn_small).pack()
            self._stat_frames[key] = vv
            # divider
            if col < 2:
                tk.Frame(stats, bg=BORDER, width=1).pack(side="left", fill="y", pady=6)

        # ── config panel ──
        cfg_frame = tk.LabelFrame(
            self, text=" Config ", fg=MUTED, bg=BG,
            font=self.fn_small, bd=1, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
        )
        cfg_frame.pack(fill="x", padx=16, pady=(0, 8))

        fields = [
            ("Video ID",         "YOUTUBE_VIDEO_ID", 22),
            ("Voice",            "VOICE",            32),
            ("Delay/char (s)",   "DELAY_PER_CHAR",   8),
            ("Max delay (s)",    "MAX_DELAY",         8),
        ]
        self._entries: dict[str, tk.Entry] = {}
        for col, (label, key, w) in enumerate(fields):
            tk.Label(cfg_frame, text=label, fg=TEXT2, bg=BG,
                     font=self.fn_label).grid(row=0, column=col*2, padx=(10,2), pady=6, sticky="e")
            e = tk.Entry(
                cfg_frame, width=w,
                bg=BG3, fg=TEXT, insertbackground=TEXT,
                relief="flat", font=self.fn_mono,
                highlightbackground=BORDER, highlightthickness=1,
            )
            e.insert(0, _cfg_get(key, ""))
            e.grid(row=0, column=col*2+1, padx=(0,10), pady=6)
            self._entries[key] = e

        # save button inline
        tk.Button(
            cfg_frame, text="Save", command=self._save_config,
            bg=BG3, fg=ACCENT, activebackground=BORDER,
            relief="flat", font=self.fn_btn, cursor="hand2",
            padx=10,
        ).grid(row=0, column=len(fields)*2, padx=(4,10), pady=6)

        # ── log box ──
        log_outer = tk.Frame(self, bg=BORDER, padx=1, pady=1)
        log_outer.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        log_inner = tk.Frame(log_outer, bg=BG2)
        log_inner.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_inner, bg=BG2, troughcolor=BG2,
                                 activebackground=BORDER, bd=0, width=10)
        scrollbar.pack(side="right", fill="y")

        self._log = tk.Text(
            log_inner,
            bg=BG2, fg=TEXT2, insertbackground=TEXT,
            relief="flat", font=self.fn_mono,
            wrap="word", state="disabled",
            yscrollcommand=scrollbar.set,
            padx=10, pady=8,
            spacing1=1, spacing3=2,
        )
        self._log.pack(fill="both", expand=True)
        scrollbar.config(command=self._log.yview)

        # text color tags
        for name, color in [
            ("green",  GREEN),
            ("blue",   BLUE),
            ("yellow", YELLOW),
            ("red",    RED),
            ("muted",  MUTED),
            ("white",  TEXT),
            ("ts",     MUTED),
        ]:
            self._log.tag_config(name, foreground=color)

        # ── bottom bar ──
        bot = tk.Frame(self, bg=BG, pady=8)
        bot.pack(fill="x", padx=16)

        self._btn_start = tk.Button(
            bot, text="▶  Start", command=self._start,
            bg=GREEN, fg=BG, activebackground="#1ab87a",
            relief="flat", font=self.fn_btn,
            cursor="hand2", padx=20, pady=6,
        )
        self._btn_start.pack(side="left", padx=(0, 8))

        self._btn_stop = tk.Button(
            bot, text="■  Stop", command=self._stop,
            bg=BG3, fg=MUTED, activebackground=BORDER,
            relief="flat", font=self.fn_btn,
            cursor="hand2", padx=20, pady=6,
            state="disabled",
        )
        self._btn_stop.pack(side="left")

        tk.Button(
            bot, text="Clear log", command=self._clear_log,
            bg=BG, fg=MUTED, activebackground=BG2,
            relief="flat", font=self.fn_small,
            cursor="hand2",
        ).pack(side="right")

    # ──────────────── config save ────────────────────────────
    def _save_config(self):
        for key, entry in self._entries.items():
            _cfg_set(key, entry.get().strip())
        self._append_log("[gui] ✅ บันทึก config แล้ว", GREEN)

    # ──────────────── start / stop ───────────────────────────
    def _start(self):
        if self._running:
            return
        if not os.path.exists(MAIN_PY):
            self._append_log(f"[gui] ❌ ไม่พบ main.py ที่ {MAIN_PY}", RED)
            return

        self._save_config()  # auto-save before start
        self._msg_count = 0
        self._restart_count = 0
        self._crash_times = []
        self._start_time = time.time()
        self._running = True

        self._stat_frames["status"].set("live")
        self._status_dot.config(fg=GREEN)
        self._btn_start.config(state="disabled", bg=BG3, fg=MUTED)
        self._btn_stop.config(state="normal", bg=RED, fg=BG)

        threading.Thread(
            target=self._watcher_loop,
            daemon=True,
            name="watcher",
        ).start()

        self._tick_uptime()
        self._append_log("[gui] 🚀 เริ่ม main.py พร้อม auto-restart", GREEN)

    def _stop(self):
        if not self._running:
            return
        self._running = False
        # watcher loop จะ terminate proc เองเมื่อเห็น _running=False
        self._set_stopped()
        self._append_log("[gui] 🛑 หยุดแล้ว", RED)

    def _set_stopped(self):
        self._running = False
        self._start_time = None
        self._stat_frames["status"].set("idle")
        self._status_dot.config(fg=MUTED)
        self._btn_start.config(state="normal", bg=GREEN, fg=BG)
        self._btn_stop.config(state="disabled", bg=BG3, fg=MUTED)
        self._uptime_var.set("")

    # ──────────────── subprocess helpers ─────────────────────
    def _spawn_proc(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-u", MAIN_PY, "--silent"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=BASE_DIR,
        )
        threading.Thread(
            target=self._read_proc,
            args=(proc,),
            daemon=True,
            name=f"reader-{proc.pid}",
        ).start()
        return proc

    def _watcher_loop(self):
        """
        Watcher รัน main.py และ auto-restart พร้อม crash backoff
        ทำงานใน daemon thread — ควบคุมด้วย self._running
        """
        self._proc = self._spawn_proc()

        while self._running:
            time.sleep(1)
            code = self._proc.poll()

            if code is None:
                continue  # ยังรันอยู่

            if not self._running:
                break  # user กด Stop

            if code == 0:
                self._log_queue.put("[watcher] ✅ main.py จบสะอาด (code 0)")
                self.after(0, self._set_stopped)
                break

            self._log_queue.put(f"[watcher] ⚠️ main.py crash (exit {code})")

            # crash accounting
            now = time.monotonic()
            self._crash_times = [t for t in self._crash_times if now - t < CRASH_WINDOW]
            self._crash_times.append(now)

            if len(self._crash_times) >= CRASH_THRESHOLD:
                self._log_queue.put(
                    f"[watcher] 🔴 crash {len(self._crash_times)} ครั้งใน {CRASH_WINDOW}s "
                    f"— backoff {BACKOFF_DELAY}s..."
                )
                # sleep in small chunks เพื่อตอบสนอง _running flag
                for _ in range(BACKOFF_DELAY):
                    if not self._running:
                        break
                    time.sleep(1)
                self._crash_times.clear()
            else:
                time.sleep(RESTART_DELAY)

            if not self._running:
                break

            self._restart_count += 1
            self.after(0, lambda: self._stat_frames["restarts"].set(
                str(self._restart_count)
            ))
            self._log_queue.put(f"[watcher] 🔄 restart #{self._restart_count}...")
            self._proc = self._spawn_proc()

        # cleanup เมื่อ loop จบ
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _read_proc(self, proc: subprocess.Popen):
        """อ่าน stdout บรรทัดต่อบรรทัดแล้วยัดใส่ queue"""
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._log_queue.put(line)
                    # นับ messages จาก 💬
                    if "💬" in line:
                        self._msg_count += 1
                        self.after(0, lambda: self._stat_frames["msgs"].set(
                            str(self._msg_count)
                        ))
        except Exception:
            pass

    # ──────────────── log poller ──────────────────────────────
    def _poll_logs(self):
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(80, self._poll_logs)

    def _append_log(self, line: str, force_color: str | None = None):
        color = force_color or _tag_color(line)
        tag = {
            GREEN:  "green",
            BLUE:   "blue",
            YELLOW: "yellow",
            RED:    "red",
            MUTED:  "muted",
            TEXT:   "white",
        }.get(color, "muted")

        self._log.config(state="normal")
        self._log.insert("end", line + "\n", tag)
        # keep max 800 lines
        lines = int(self._log.index("end-1c").split(".")[0])
        if lines > 800:
            self._log.delete("1.0", f"{lines - 800}.0")
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    # ──────────────── uptime tick ─────────────────────────────
    def _tick_uptime(self):
        if not self._running or self._start_time is None:
            return
        elapsed = int(time.time() - self._start_time)
        h, r = divmod(elapsed, 3600)
        m, s = divmod(r, 60)
        self._uptime_var.set(f"uptime {h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._tick_uptime)

    # ──────────────── close ───────────────────────────────────
    def _on_close(self):
        self._stop()
        self.after(300, self.destroy)


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()