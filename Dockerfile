# ใช้ Python 3.10 เป็นฐาน
FROM python:3.10-slim

# กำหนดโฟลเดอร์ทำงาน
WORKDIR /app

# ติดตั้ง ffmpeg ให้เครื่องเซิร์ฟเวอร์
RUN apt-get update && apt-get install -y ffmpeg nodejs

# ก๊อปปี้ requirements และติดตั้ง พร้อมบังคับอัปเดต yt-dlp ให้ใหม่ที่สุดเสมอ!
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install -U yt-dlp

# ก๊อปปี้โค้ดทั้งหมดของเราลงไป
COPY . .

# สร้างโฟลเดอร์สำหรับอัปโหลด
RUN mkdir -p temp_uploads

# คำสั่งรันเซิร์ฟเวอร์
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]