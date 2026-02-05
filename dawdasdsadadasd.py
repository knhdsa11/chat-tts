from gtts import gTTS
import os

# ข้อความที่ต้องการแปลง
text = "สวัสดีครับ นี่คือเสียงจาก gTTS"

# สร้างออบเจกต์ gTTS (กำหนดภาษาเป็นไทย 'th')
tts = gTTS(text=text, lang='th', slow=False)

# บันทึกไฟล์เสียง
tts.save("output.mp3")