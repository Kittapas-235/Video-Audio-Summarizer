# services/ai_engine.py
import os
import time
import json
import re
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def get_fallback_data(error_msg):
    """ สร้างข้อมูลสำรองเมื่อเกิด Error """
    return {
        "speaker_info": "ไม่สามารถวิเคราะห์ได้",
        "summary_points": ["เกิดข้อผิดพลาด: " + str(error_msg)],
        "key_takeaways": "กรุณาลองใหม่อีกครั้ง",
        "quizzes": [
            {
                "id": 1, 
                "type": "multiple_choice", 
                "question": "เกิดข้อผิดพลาดในการเชื่อมต่อ AI", 
                "options": ["Error", "Error", "Error", "Error"], 
                "correct_answer_index": 0,
                "explanation": "กรุณาเช็คอินเทอร์เน็ตหรือ API Key"
            }
        ]
    }

def clean_json_response(text):
    """ แกะ JSON ออกจาก Markdown """
    try:
        clean_text = re.sub(r'```json\s*', '', text)
        clean_text = re.sub(r'```\s*', '', clean_text)
        clean_text = clean_text.strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"❌ JSON Parse Error: {e}")
        return get_fallback_data(f"AI ตอบกลับผิดรูปแบบ ({e})")

def summarize_video(video_path: str, num_questions: int = 5, difficulty: str = "medium"):
    try:
        print(f"📤 Uploading: {video_path}")
        video_file = genai.upload_file(path=video_path)
        
        # รอ Process
        while video_file.state.name == "PROCESSING":
            print("⏳ Processing video...")
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            return get_fallback_data("Google Server Process Video Failed")

        print("✅ Analyzing content...")

        # --- ใช้ gemini-1.5-flash (รองรับวิดีโอ) ---
        model = genai.GenerativeModel('gemini-flash-latest')
        
        # กำหนดคำอธิบายความยากให้ AI
        difficulty_context = {
            "easy": "เน้นนิยาม ความหมายพื้นฐาน และคำศัพท์ที่ปรากฏชัดเจนในวิดีโอ",
            "medium": "เน้นความเข้าใจในเนื้อหา สามารถสรุปใจความสำคัญและเชื่อมโยงประเด็นได้",
            "hard": "เน้นการวิเคราะห์ การประยุกต์ใช้ และการตีความจากสิ่งที่ผู้พูดสื่อสาร"
        }

        # สร้าง Prompt ที่รวมทุกเงื่อนไข
        prompt = f"""
        วิเคราะห์วิดีโอนี้ แล้วตอบกลับเป็น JSON Format เท่านั้น โดยมีโครงสร้างดังนี้:
        {{
            "speaker_info": "ชื่อผู้พูด และข้อมูลแนะนำตัว (ภาษาไทย)",
            "summary_points": [
                {{"time": "นาที:วินาที", "text": "สรุปเนื้อหาที่เริ่มในเวลานี้"}}
            ],
            "key_takeaways": "สิ่งที่ได้รับจากการดูคลิปนี้ (สั้นๆ ภาษาไทย)",
            "quizzes": [
                {{
                    "id": 1,
                    "type": "multiple_choice",
                    "question": "คำถาม...",
                    "options": ["ตัวเลือก 1", "ตัวเลือก 2", "ตัวเลือก 3", "ตัวเลือก 4"],
                    "correct_answer_index": 0,
                    "explanation": "คำอธิบายเฉลย"
                }}
            ]
        }}
        
        ข้อกำหนดพิเศษ:
        1. ใน summary_points ต้องระบุเวลา 'time' (MM:SS) ให้สัมพันธ์กับเนื้อหาจริง
        2. สร้างแบบทดสอบ (Quiz) จำนวน {num_questions} ข้อ
        3. ระดับความยากคือ: {difficulty} ({difficulty_context.get(difficulty)})
        4. ใช้ภาษาไทยเป็นหลัก
        """
        
        # เพิ่ม request_options เพื่อแก้ปัญหา EOF / Connection Timeout
        response = model.generate_content(
            [video_file, prompt],
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": 600} # เพิ่มเวลา Timeout เป็น 10 นาที
        )
        
        return clean_json_response(response.text)

    except Exception as e:
        print(f"❌ General Error: {e}")
        return get_fallback_data(str(e))