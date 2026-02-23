import os
import re
import sys
import time
import subprocess
from datetime import datetime

import pytchat
from playsound3 import playsound

from app.config import DEFAULT_VOICE, MAX_PLAY_DURATION_SECONDS
from app.utils import extract_video_id


def load_voices() -> list[str]:
    voices: list[str] = []
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "edge_tts", "--list-voices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        out = proc.stdout + "\n" + proc.stderr
        ids = re.findall(r"[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural", out)
        seen: set[str] = set()
        for voice_id in ids:
            if voice_id not in seen:
                seen.add(voice_id)
                voices.append(voice_id)
    except Exception:
        return [DEFAULT_VOICE, "en-US-AriaNeural", "en-US-GuyNeural"]

    if not voices:
        voices = [DEFAULT_VOICE, "en-US-AriaNeural", "en-US-GuyNeural"]
    return voices


def chat_reader_process(url: str, ipc_queue) -> None:
    try:
        video_id = extract_video_id(url)
        chat = pytchat.create(video_id=video_id)
        while chat.is_alive():
            for chat_item in chat.get().sync_items():
                ipc_queue.put({"author": chat_item.author.name, "message": chat_item.message})
            time.sleep(0.4)
    except Exception as exc:
        ipc_queue.put(f"[ERROR_CHAT] {exc}")


def generate_tts_file(text: str, voice: str, temp_dir: str) -> tuple[bool, str, str]:
    filename = os.path.join(temp_dir, f"tts_{int(time.time() * 1000)}.mp3")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            "--text",
            text,
            "--write-media",
            filename,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "unknown error").strip()
        return False, filename, err
    if not os.path.exists(filename):
        return False, filename, "missing output file"
    return True, filename, ""


def play_audio_non_blocking(filename: str, stop_event, logger) -> None:
    player = playsound(filename, block=False)
    start_time = time.time()
    while player.is_alive():
        if stop_event.is_set():
            player.stop()
            break
        if time.time() - start_time > MAX_PLAY_DURATION_SECONDS:
            player.stop()
            logger("[WARN] playback timeout, stop forced")
            break
        time.sleep(0.08)


def cleanup_old_tts_files(temp_dir: str, max_keep: int, logger) -> None:
    files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith(".mp3")]
    files.sort(key=os.path.getmtime, reverse=True)
    for old_file in files[max_keep:]:
        try:
            os.remove(old_file)
        except OSError as exc:
            logger(f"[WARN] ลบไฟล์ไม่สำเร็จ: {old_file} ({exc})")


def prune_recent_messages(recent_messages: dict, max_keys: int) -> None:
    if len(recent_messages) <= max_keys:
        return
    oldest = sorted(
        recent_messages.items(),
        key=lambda item: item[1][-1] if item[1] else datetime.min,
    )
    for key, _ in oldest[: len(recent_messages) - max_keys]:
        recent_messages.pop(key, None)
