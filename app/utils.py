import os
import re
from dataclasses import dataclass


@dataclass
class DelayConfig:
    per_char: float
    minimum: int
    maximum: int

    def normalized(self) -> "DelayConfig":
        per_char = 0.0 if self.per_char < 0 else self.per_char
        minimum = 0 if self.minimum < 0 else self.minimum
        maximum = minimum if self.maximum < minimum else self.maximum
        return DelayConfig(per_char=per_char, minimum=minimum, maximum=maximum)


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def extract_video_id(url: str) -> str:
    patterns = [
        r"[?&]v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/live/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url.strip()
