import os
import time
import json
import re
import subprocess
import google.generativeai as genai
from dotenv import load_dotenv
from google.generativeai.types import HarmCategory, HarmBlockThreshold

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def get_fallback_data(error_msg):
    """ สร้างข้อมูลสำรองเมื่อเกิด Error (อัปเดตเพิ่ม flashcards) """
    return {
        "speaker_info": "Unknown Speaker",
        "summary_points": [{"time": "00:00", "text": "Error: " + str(error_msg)}],
        "comprehensive_summary": "### Error\nAn error occurred while generating the study guide.",
        "key_takeaways": "Please try again later.",
        "flashcards": [],
        "quizzes": [
            {
                "id": 1, 
                "type": "multiple_choice", 
                "question": "AI Connection Error", 
                "options": ["Error", "Error", "Error", "Error"], 
                "correct_answer_index": 0,
                "explanation": "Please check your API key or internet connection."
            }
        ]
    }

def clean_json_response(text):
    """ แกะ JSON ออกจาก Markdown และซ่อมแซม Backslash """
    try:
        clean_text = re.sub(r'```json\s*', '', text)
        clean_text = re.sub(r'```\s*', '', clean_text)
        clean_text = clean_text.strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"❌ JSON Parse Error: {e}")
        return get_fallback_data(f"AI ตอบกลับผิดรูปแบบ ({e})")

def extract_audio_for_ai(video_path: str) -> str:
    """ แยกเฉพาะเสียง (m4a) ออกจากไฟล์วิดีโอ เพื่อให้ AI สรุปเร็วขึ้น 10 เท่า! """
    audio_path = video_path.rsplit('.', 1)[0] + "_audio.m4a"
    try:
        print(f"🎵 Extracting audio to speed up AI... (This takes 1-2 seconds)")
        command = [
            'ffmpeg', '-i', video_path, 
            '-vn', '-c:a', 'aac', '-b:a', '64k', 
            audio_path, '-y'
        ]
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return audio_path
    except Exception as e:
        print(f"⚠️ Audio extraction failed, fallback to original video: {e}")
        return video_path

def summarize_video(video_path: str, num_questions: int = 5, difficulty: str = "medium", include_written: bool = False):
    try:
        # 🚀 1. เช็กว่าไฟล์ไม่ได้เป็นไฟล์เสียงอยู่แล้ว ให้ดึงเสียงออกมาก่อน (รองรับ mp4, mov ฯลฯ)
        audio_exts = ('.mp3', '.m4a', '.wav', '.ogg', '.aac', '.flac')
        if not video_path.lower().endswith(audio_exts) and "upload_" in os.path.basename(video_path):
            video_path = extract_audio_for_ai(video_path)

        print(f"📤 Uploading: {video_path}")
        video_file = genai.upload_file(path=video_path)
        
        while video_file.state.name == "PROCESSING":
            print("⏳ Processing file...")
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            return get_fallback_data("Google Server Process Failed")

        print("✅ Analyzing content...")

        if include_written:
            quiz_types_instruction = 'สุ่มผสมกันทั้ง 3 รูปแบบคือ "multiple_choice", "true_false" และ "short_answer" (ข้อเขียน)'
        else:
            quiz_types_instruction = 'สุ่มผสมกันเฉพาะ 2 รูปแบบคือ "multiple_choice" และ "true_false" เท่านั้น (ห้ามทำแบบข้อเขียน)'

        # System Prompt (อัปเกรดเป็นระดับผู้เชี่ยวชาญ)
        system_prompt = """
        คุณคือ "ผู้ช่วยสรุปเนื้อหาและติวเตอร์ส่วนตัว" หน้าที่ของคุณคือฟังเนื้อหา แล้วสรุปออกมาให้เป็นระเบียบ เข้าใจง่าย และถูกต้องตามคลิปวิดีโอ 100%
        
        คำสั่งพิเศษ (สำคัญมาก):
        1. "อิงจากเนื้อหาจริงเท่านั้น (Strict Grounding)": ให้สรุปเฉพาะหัวข้อ ทฤษฎี หรือสูตรสมการที่ "ผู้พูดเอ่ยถึงหรือแสดงให้เห็นในคลิปเท่านั้น" ห้ามนำความรู้ภายนอก ห้ามเพิ่มสมการขั้นสูง หรือห้ามเพิ่มทฤษฎีที่ไม่ได้อยู่ในคลิปเข้ามาผสมเด็ดขาด เพื่อป้องกันผู้เรียนสับสน
        2. "วิเคราะห์เชิงลึก (Why & How)": อย่าสรุปแค่ว่าคลิปนี้ทำอะไร แต่ต้องอธิบายด้วยว่า "ทำไมถึงทำแบบนั้น", "หลักการทำงานคืออะไร", และ "ข้อดี/ข้อเสียคืออะไร"
        3. "ตอบคำถามวิจารณ์ผล (Critical Analysis)": หากในคลิปมีการเปรียบเทียบ (เช่น Rule-based vs ML-based) หรือมีการตั้งคำถามทิ้งท้าย คุณต้องวิจารณ์ เปรียบเทียบ และแนะนำวิธีการปรับปรุงประสิทธิภาพของแต่ละวิธีอย่างละเอียดระดับผู้เชี่ยวชาญ
        4. เนื่องจากคุณอาจได้รับเพียงข้อมูลเสียง (ไม่มีภาพ) ให้คุณ "วิเคราะห์บริบทเชิงลึก" หากผู้พูดอธิบายถึงคอนเซปต์ ทฤษฎี หรือการคำนวณ แต่ไม่ได้พูด "สูตร" หรือ "โค้ด" ออกมาตรงๆ ให้ใช้ความรู้ของคุณดึงสูตรสมการ ทฤษฎี หรือคำศัพท์เฉพาะทางที่เกี่ยวข้องออกมาใส่ใน Flashcards หรือ Summary ด้วยตัวเองทันที เสมือนว่าคุณเห็นภาพบนกระดานนั้นจริงๆ
        5. กฎเรื่องภาษา (สำคัญ): ให้สร้างเนื้อหาสรุปและแบบทดสอบทั้งหมด "ตามภาษาหลักที่ใช้ในคลิปวิดีโอ" (เช่น ถ้าคลิปพูดภาษาไทย ให้พิมพ์ผลลัพธ์เป็นภาษาไทยทั้งหมด, ถ้าคลิปภาษาอังกฤษ ให้พิมพ์เป็นภาษาอังกฤษทั้งหมด)
        """
        
        model = genai.GenerativeModel(
            model_name='gemini-flash-latest',
            system_instruction=system_prompt
        )
        
        difficulty_context = {
            "easy": "เน้นนิยาม ความหมายพื้นฐาน",
            "medium": "เน้นความเข้าใจและการเชื่อมโยงประเด็น",
            "hard": "เน้นการวิเคราะห์และการประยุกต์ใช้ขั้นสูง"
        }

        # 🚀 2. โครงสร้าง JSON ภาษาไทย (คงรูปแบบเดิม แต่บังคับเพิ่มหัวข้อวิเคราะห์)
        prompt = f"""
        วิเคราะห์เนื้อหานี้ แล้วตอบกลับเป็น JSON Format เท่านั้น โดยมีโครงสร้างดังนี้:
        {{
            "speaker_info": "ชื่อผู้พูด และข้อมูลแนะนำตัว",
            "summary_points": [
                {{"time": "MM:SS", "text": "สรุปเนื้อหาสั้นๆ ในช่วงเวลานี้"}}
            ],
            "comprehensive_summary": "สรุปรวมเนื้อหาทั้งหมดอย่างละเอียด จัดรูปแบบเป็น Markdown (ใช้ # สำหรับหัวข้อหลัก, - สำหรับข้อย่อย, **ข้อความ** สำหรับเน้นคำ และ \\[ ... \\] สำหรับสูตรคณิตศาสตร์)\\n\\n*(ตอบคำถามสำคัญ เปรียบเทียบ และแนะนำวิธีปรับปรุงโมเดลหรือวิธีการต่างๆ อย่างละเอียด)*",
            "key_takeaways": "สิ่งที่ได้รับสั้นๆ หรือใจความสำคัญ",
            "flashcards": [
                {{
                    "front": "หัวข้อ/สูตร/คำศัพท์",
                    "back": "คำอธิบาย/คำตอบ/นิยาม",
                    "type": "math หรือ concept"
                }}
            ],
            "quizzes": [
                {{
                    "id": 1,
                    "type": "multiple_choice",
                    "question": "คำถามเชิงวิเคราะห์แบบเลือกตอบ...",
                    "options": ["ตัวเลือก 1", "ตัวเลือก 2", "ตัวเลือก 3", "ตัวเลือก 4"],
                    "correct_answer_index": 0,
                    "explanation": "เฉลยและคำอธิบาย"
                }},
                {{
                    "id": 2,
                    "type": "short_answer",
                    "question": "คำถามแบบเขียนตอบ (เช่น ให้อธิบายข้อดีข้อเสีย... หรือ จงเปรียบเทียบ...)",
                    "suggested_answer": "แนวคำตอบที่ถูกต้องและสมบูรณ์",
                    "keywords": ["คำหลักที่1", "คำหลักที่2", "คำหลักที่3"]
                }},
                {{
                    "id": 3,
                    "type": "true_false",
                    "question": "ข้อความนี้ถูกหรือผิด: [ใส่ข้อความที่ต้องการทดสอบ]...",
                    "options": ["ถูก (True)", "ผิด (False)"],
                    "correct_answer_index": 0,
                    "explanation": "เฉลยเหตุผลว่าทำไมถึงถูกหรือผิด"
                }}
            ]
        }}
        
        ข้อกำหนดพิเศษ:
        1. สร้างแบบทดสอบจำนวน {num_questions} ข้อ โดย {quiz_types_instruction} ระดับความยาก: {difficulty} ({difficulty_context.get(difficulty, 'medium')})
        2. สร้าง Flashcards จำนวน 5-10 ใบ เพื่อช่วยจำประเด็นสำคัญ
        3. กฎเรื่องภาษา: สรุปผลลัพธ์และคำถามทั้งหมดให้สอดคล้องกับภาษาต้นฉบับของสื่อ
        4. หากมีสูตรคณิตศาสตร์ ให้เขียนในรูปแบบ LaTeX (เช่น \\frac{{a}}{{b}})
        
        ข้อกำหนดพิเศษเรื่องสูตร:
        1. หากมีสูตรคณิตศาสตร์หรือสัญลักษณ์ฟิสิกส์ ให้ครอบด้วยเครื่องหมาย \\( ... \\) สำหรับสูตรในบรรทัด
        หรือ \\[ ... \\] สำหรับสูตรที่แยกบรรทัดเสมอ
        เช่น \\( F = ma \\) หรือ \\( F_{{component}} = F \\cos \\theta \\)
        2. ใช้ตัวอักษรแบบมาตรฐาน LaTeX เพื่อความสวยงาม
        """
        
        safety_settings = [
            {
                "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
                "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
        ]

        response = model.generate_content(
            [video_file, prompt],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "top_p": 0.8
            },
            safety_settings=safety_settings,
            request_options={"timeout": 600}
        )

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            return get_fallback_data("Content blocked due to Safety Filter.")

        return clean_json_response(response.text)

    except Exception as e:
        error_str = str(e)
        
        # 🛡️ ระบบจัดหน้าตา Error ให้สวยงามและเป็นมิตรกับผู้ใช้งาน
        friendly_error = "An error occurred during processing. Please try again."
        
        if "429" in error_str or "quota" in error_str.lower():
            friendly_error = "⏳ AI system is currently overloaded (Quota limit). Please wait 1-2 minutes and try again."
        elif "finish_reason: SAFETY" in error_str:
             friendly_error = "⚠️ AI blocked the request due to safety policy violations (Inappropriate content)."
        elif "API_KEY" in error_str or "API key" in error_str:
            friendly_error = "🔑 Cannot connect to Google AI (Invalid API Key)."
        elif "503" in error_str or "overloaded" in error_str.lower():
            friendly_error = "🔥 Google AI servers are overloaded. Please try again later."
        elif "JSON Parse Error" in error_str or "Invalid \\escape" in error_str:
            friendly_error = "🧩 Data formatting error (JSON Error). Please analyze the video again."
        else:
            # ถ้าเป็น Error ประหลาดๆ อื่นๆ ให้ตัดข้อความสั้นๆ ไม่ให้พ่นโค้ดยาวเกินไป
            friendly_error = f"🛠️ Technical error: {error_str[:80]}..."

        print(f"❌ General Error: {error_str}")
        return get_fallback_data(friendly_error)

def ask_ai_tutor(message: str, context: str) -> str:
    """สมองกลของ Chatbot ไว้ตอบคำถามจากหน้าสรุป"""
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        prompt = f"""
        คุณคือ "AI Tutor" ผู้ช่วยตอบคำถามที่ใจดีและอธิบายเข้าใจง่าย
        หน้าที่ของคุณคือตอบคำถาม โดยอิงจากเนื้อหาบทเรียนที่ให้มานี้เป็นหลัก:
        
        [เนื้อหาบทเรียน]
        {context}
        
        คำถาม: {message}
        
        ข้อบังคับ:
        1. ตอบให้ตรงประเด็น อธิบายให้เข้าใจง่าย จัดรูปแบบให้อ่านง่าย
        2. ถ้าคำถามไม่อยู่ในเนื้อหาบทเรียน ให้ตอบจากข้อมูลทั่วไปแล้วค่อยอธิบายเสริม
        3. ตอบเป็นภาษาไทย หรือภาษาเดียวกับที่นักเรียนถาม
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        print(f"❌ Chatbot Error: {e}")
        return "Error Please ask again"