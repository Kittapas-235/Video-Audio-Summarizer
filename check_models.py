# check_models.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

# โหลด Key
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ ไม่พบ API Key ในไฟล์ .env กรุณาตรวจสอบ")
else:
    genai.configure(api_key=api_key)
    print("🔍 กำลังดึงรายชื่อโมเดลที่คุณใช้ได้...")
    try:
        # ดึงรายชื่อโมเดลทั้งหมด
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ พบโมเดล: {m.name}")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")