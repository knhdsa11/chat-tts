<div align="center">

# chat-tts

**อ่านแชท YouTube Live ออกเสียงอัตโนมัติด้วย Edge TTS**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square&logo=windows&logoColor=white)](https://github.com/knhdsa11/chat-tts)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![edge-tts](https://img.shields.io/badge/edge--tts-6.1.9%2B-orange?style=flat-square)](https://github.com/rany2/edge-tts)

> ดึงแชทจาก YouTube Live แบบ real-time → สังเคราะห์เสียงด้วย Microsoft Edge TTS → เล่นเสียงออกลำโพงอัตโนมัติ

<!--
  แนะนำ: ใส่ภาพ screenshot หรือ demo gif ตรงนี้
  ![demo](assets/demo.gif)
-->

</div>

---

## Features

- ดึงแชทจาก YouTube Live ผ่าน HTTP โดยตรง — ไม่ต้องใช้ API key
- สังเคราะห์เสียงด้วย `edge-tts` รองรับเสียงภาษาไทยหลายแบบ
- GUI แยกต่างหาก (`GUI.py`) พร้อม auto-restart เมื่อ backend crash
- Auto-reconnect เมื่อแชทหลุด
- ตั้งค่าได้ผ่าน `config.ini` โดยไม่ต้องแตะโค้ด

---

## Requirements

- Windows 10/11
- Python 3.10+
- Internet connection

---

## Installation

```bash
# 1. clone repo
git clone https://github.com/knhdsa11/chat-tts.git
cd chat-tts

# 2. ติดตั้ง dependencies
pip install -r requirements.txt
```

หรือใช้ script อัตโนมัติ (สร้าง venv + ติดตั้ง + รันให้เลย):

```bat
Chattts.cmd
```

---

## Usage

**รันผ่าน GUI** (แนะนำ):
```bash
python main.py
```

**รัน backend ตรงๆ** (headless):
```bash
python api.py
```

1. เปิด YouTube Live stream ที่ต้องการ
2. คัดลอก Video ID จาก URL (เช่น `https://youtube.com/watch?v=`**`fiss3CP8-BY`**)
3. ใส่ Video ID ใน `config.ini` หรือช่อง Video ID ใน GUI
4. กด **Start**

---

## Configuration

แก้ไขที่ `config.ini` หรือผ่าน GUI โดยตรง:

| Key | Default | Description |
|---|---|---|
| `youtube_video_id` | `fiss3CP8-BY` | Video ID ของ stream ที่ต้องการ |
| `voice` | `th-TH-PremwadeeNeural` | เสียงที่ใช้สังเคราะห์ ([รายชื่อเสียงทั้งหมด](https://github.com/rany2/edge-tts#voices)) |
| `delay_per_char` | `3` | หน่วงเวลาต่อตัวอักษร (วินาที) หลังอ่านจบ |
| `max_delay` | `5` | หน่วงเวลาสูงสุดต่อข้อความ (วินาที) |
| `clear_every` | `10` | ล้าง TTS cache ทุกกี่ข้อความ |

**ตัวอย่าง `config.ini`:**
```ini
[settings]
youtube_video_id = fiss3CP8-BY
voice = th-TH-PremwadeeNeural
delay_per_char = 3
max_delay = 5
clear_every = 10
```

---

## Project Structure

```
chat-tts/
├── api.py           # backend หลัก — YouTube chat reader + TTS worker
├── main.py          # GUI dashboard + watcher (auto-restart)
├── config.ini       # ตั้งค่าทั้งหมด
├── requirements.txt
└── Chattts.cmd      # Windows helper — setup venv + run
```

---

## Roadmap

- [ ] รองรับ URL แบบเต็ม (ไม่ต้องคัดลอก Video ID เอง)
- [ ] เพิ่ม spam filter / blacklist คำ
- [ ] เลือกเสียงได้จาก dropdown ใน GUI
- [ ] รองรับ Twitch chat
- [ ] build เป็น `.exe` standalone

---

## Voices (ตัวอย่างภาษาไทย)

| Voice | สไตล์ |
|---|---|
| `th-TH-PremwadeeNeural` | หญิง — เป็นธรรมชาติ (default) |
| `th-TH-NiwatNeural` | ชาย |
| `th-TH-AcharaNeural` | หญิง — เป็นทางการ |

ดูรายชื่อเสียงทั้งหมดด้วย:
```bash
python -m edge_tts --list-voices | grep th-TH
```