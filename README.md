# 🎓 LectureLens (VA-Summar)

**AI-Powered Interactive Video Learning Platform**

LectureLens เป็นเว็บแอปพลิเคชันที่ช่วยแปลงวิดีโอเลกเชอร์ยาวๆ หรือคลิปจาก YouTube ให้กลายเป็นบทเรียนแบบ Interactive (สรุปเนื้อหา, แฟลชการ์ด, แบบทดสอบ และ AI Tutor) ภายในไม่กี่นาที เพื่อช่วยให้การเรียนรู้รวดเร็วและมีประสิทธิภาพมากขึ้น

## ✨ Features (ฟีเจอร์เด่น)

- **📹 Universal Upload:** รองรับการอัปโหลดไฟล์วิดีโอ/เสียงจากในเครื่อง หรือแปะลิงก์ YouTube
- **📝 Smart Study Guide:** สรุปเนื้อหาอัตโนมัติ จัดรูปแบบด้วย Markdown และแสดงสมการคณิตศาสตร์ (LaTeX) ได้อย่างสมบูรณ์แบบ
  - รองรับการ Export เนื้อหาเป็นไฟล์ PDF สำหรับอ่านแบบออฟไลน์
- **🗂️ Interactive Flashcards:** ทบทวนความจำด้วยระบบแฟลชการ์ดแบบพลิกหน้า-หลัง
- **🧠 Adaptive Quizzes:** - สร้างข้อสอบอัตโนมัติจากเนื้อหา (Multiple Choice & Written Response)
  - สั่ง AI เจนข้อสอบเพิ่มได้ตามจำนวนและความยากที่ต้องการ
- **🤖 AI Tutor Chatbot:** แชทบอทประจำบทเรียนที่รู้บริบทของวิดีโอ สามารถถาม-ตอบข้อสงสัยได้ทันที
- **🖥️ Resizable UI:** อินเทอร์เฟซแบบลากขยายหน้าจอได้ (Split-pane) มอบประสบการณ์การใช้งานระดับ Desktop App

## 🛠️ Tech Stack (เทคโนโลยีที่ใช้)

- **Backend:** Python, FastAPI, Uvicorn
- **Frontend:** HTML5, CSS3, JavaScript, Bootstrap 5
- **AI Engine:** Google Gemini API
- **Tools:** yt-dlp (ดาวน์โหลดวิดีโอ), html2pdf (แปลง PDF), MathJax (เรนเดอร์สูตรเลข)

## ⚙️ Installation (การติดตั้ง)

1. **Clone repository หรือดาวน์โหลดซอร์สโค้ด**
2. **สร้าง Virtual Environment (แนะนำ)**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # สำหรับ Windows
3. **ติดตั้ง Libraries ที่จำเป็น**
   ```bash
   pip install fastapi uvicorn yt-dlp google-generativeai pydantic jinja2 python-multipart
4. **ตั้งค่า API Key**
   - สร้างไฟล์ .env ไว้ที่โฟลเดอร์หลัก
   - เพิ่มบรรทัดนี้ลงไป:
   ```bash
   GOOGLE_API_KEY=your_gemini_api_key_here

## 🚀 How to Run (วิธีใช้งาน)

- run python main.py
- จากนั้นเปิดเบราว์เซอร์แล้วไปที่: http://localhost:8000
- Enjoy your journey ✨