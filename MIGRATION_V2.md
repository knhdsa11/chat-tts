# Migration note: stable modular entrypoint

- Old files are kept as requested (`main.py`, `main1.py`, `blackup.py`, `main_v2.py`).
- New recommended entrypoint is `main_v3.py`.
- v3 splits logic into multiple files under `app/` for easier maintenance.

## Run
```bash
python main_v3.py
```

## Structure
- `app/config.py` : constants and runtime limits (including TTS cache cap = 10 files)
- `app/utils.py` : generic helpers (`DelayConfig`, directory setup, URL parsing)
- `app/services.py` : chat worker, voice loader, TTS generation/playback, cleanup helpers
- `app/ui.py` : Tkinter UI + orchestration logic

## Key fixes kept/improved
- Delay validation and normalization.
- Better YouTube video-id extraction (`watch`, `youtu.be`, `live`, `shorts`, `embed`).
- Global pruning for spam-tracking memory growth.
- Consistent lowercase blacklist handling.
- Auto-remove old `.mp3` files after playback, keeping latest 10 files.

## Windows helper scripts
- `run_app.cmd` : create/use `.venv`, install deps, run `main_v3.py`.
- `pyinstaller.cmd` : create/use `.venv`, install deps + pyinstaller, build Windows executable into `dist\chat-tts\`.
