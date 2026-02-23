# Bug Audit (Chat-TTS)

Date: 2026-02-23

## Scope checked
- `main.py`
- `main1.py`
- `requirements.txt`
- Utility scripts: `blackup.py`, `Untitled-1.py`, `dawdasdsadadasd.py`

## Summary
- **Critical/High:** 3
- **Medium:** 4
- **Low:** 3
- **Total findings:** 10

## Findings

### 1) Missing runtime dependency for `main.py` (High)
`main.py` imports `playsound3`, but `requirements.txt` does not include `playsound3`.
This can cause immediate startup failure in environments created from `requirements.txt`.

### 2) `main1.py` imports modules that are not used (Low)
`main1.py` imports `filedialog`, `shutil`, and `json` but does not use them.
This is not a crash bug but indicates code drift and maintainability issues.

### 3) Case handling bug in blacklist add flow (Medium)
In `main1.py`, profanity words are checked with original casing (`p not in self.profanity_list`) but stored as lowercase (`p.lower()`).
This can report added words incorrectly and create inconsistent behavior when users enter mixed-case text.

### 4) Over-broad exception handling hides real errors (Medium)
Both `main.py` and `main1.py` contain many bare/blanket `except` blocks.
This suppresses tracebacks and makes production bugs hard to diagnose.

### 5) No validation for delay ranges / negative values (Medium)
`min_delay`, `max_delay`, and `delay_per_char` are user-editable without validation.
Negative or invalid values can cause odd pacing behavior and edge-case failures.

### 6) Spam tracking dictionary can grow without global cleanup (Medium)
`recent_messages` is cleaned only per active key, not globally.
Long-running sessions with many unique messages/users may cause unbounded memory growth.

### 7) Playback timeout hardcoded and may cut long messages (Low)
`main.py` enforces `max_play_duration = 45.0` seconds.
Very long synthesized speech can be terminated early.

### 8) Video ID extraction is incomplete for all YouTube URL variants (Low)
Regex only handles classic `v=` and `youtu.be/` formats.
Other common URLs (`/live/`, `shorts/`, query variants) may fail and produce chat read errors.

### 9) Repo contains throwaway utility scripts without context (Low)
`blackup.py`, `Untitled-1.py`, and `dawdasdsadadasd.py` appear unrelated to app runtime.
This increases noise and confusion when debugging.

### 10) Duplicate entry points with diverging implementations (High)
Both `main.py` and `main1.py` are full app implementations with different audio stacks.
Parallel versions increase bug surface and make fixes easy to miss in one path.

## Checks executed
- `python -m py_compile main.py main1.py blackup.py Untitled-1.py dawdasdsadadasd.py`
- Manual static review for imports, queue/process flow, validation and error handling.

