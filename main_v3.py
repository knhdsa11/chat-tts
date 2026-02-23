import multiprocessing
import tkinter as tk

from app.config import LOG_DIR, TEMP_DIR
from app.ui import YouTubeTTSApp
from app.utils import safe_mkdir


def main() -> None:
    multiprocessing.freeze_support()
    safe_mkdir(TEMP_DIR)
    safe_mkdir(LOG_DIR)

    root = tk.Tk()
    app = YouTubeTTSApp(root)
    app.log("[SYSTEM] พร้อมทำงาน ✅ (v3 modular)")
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_system(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
