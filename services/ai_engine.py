import os
import time
import json
import docx
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
    """ แกะ JSON ออกจาก Markdown และใส่เกราะป้องกัน (Fallback Keys) """
    try:
        clean_text = re.sub(r'```json\s*', '', text)
        clean_text = re.sub(r'```\s*', '', clean_text)
        clean_text = clean_text.strip()
        
        # สเต็ป 1: ปกป้องคำสั่ง JSON ที่ถูกต้องอยู่แล้ว (เอาไปซ่อนไว้ก่อน)
        clean_text = clean_text.replace('\\\\', '__DBL__') # ปกป้อง \\
        clean_text = clean_text.replace('\\"', '__QOT__')  # ปกป้อง \"
        clean_text = clean_text.replace('\\n', '__NL__')   # ปกป้อง \n
        clean_text = clean_text.replace('\\t', '__TAB__')  # ปกป้อง \t
        clean_text = clean_text.replace('\\r', '__CR__')   # ปกป้อง \r
        
        # สเต็ป 2: ค้นหาเศษซาก \ โดดๆ จาก LaTeX (เช่น \frac, \theta) แล้วเบิ้ลให้มัน
        clean_text = clean_text.replace('\\', '\\\\')
        
        # สเต็ป 3: คืนร่างเดิมให้กับคำสั่ง JSON ที่เราแอบซ่อนไว้
        clean_text = clean_text.replace('__DBL__', '\\\\')
        clean_text = clean_text.replace('__QOT__', '\\"')
        clean_text = clean_text.replace('__NL__', '\\n')
        clean_text = clean_text.replace('__TAB__', '\\t')
        clean_text = clean_text.replace('__CR__', '\\r')

        parsed_data = json.loads(clean_text)

        # 🛡️ โล่ชั้นที่ 1: ตรวจสอบและเติม Key หลักที่ AI อาจจะลืมสร้างให้ครบเสมอ
        safe_data = {
            "speaker_info": parsed_data.get("speaker_info", "Unknown Speaker"),
            "summary_points": parsed_data.get("summary_points", []),
            "comprehensive_summary": parsed_data.get("comprehensive_summary", "ไม่มีข้อมูลสรุปแบบละเอียดในวิดีโอนี้"),
            "key_takeaways": parsed_data.get("key_takeaways", ""),
            "flashcards": parsed_data.get("flashcards", []),
            "quizzes": []
        }
        
        # 🛡️ โล่ชั้นที่ 2: เช็กย่อยใน Quizzes ป้องกันหน้าเว็บพังตอนกดปุ่ม
        raw_quizzes = parsed_data.get("quizzes", [])
        for q in raw_quizzes:
            if q.get("type") == "short_answer":
                # ถ้า AI ลืมใส่คีย์ให้ข้อเขียน ให้เติมค่าว่างลงไป (Jinja2 จะได้ไม่ฟ้อง Undefined)
                q["keywords"] = q.get("keywords", [])
                q["suggested_answer"] = q.get("suggested_answer", "ไม่มีแนวคำตอบ")
            elif q.get("type") in ["multiple_choice", "true_false"]:
                # ถ้า AI ลืมใส่ options ให้ข้อสอบ
                q["options"] = q.get("options", ["A", "B", "C", "D"])
                
            safe_data["quizzes"].append(q)

        return safe_data
        
    except Exception as e:
        print(f"❌ JSON Parse Error: {e}")
        return get_fallback_data(f"AI ตอบกลับผิดรูปแบบ ({e})")

def extract_audio_for_ai(video_path: str) -> str:
    """ แยกเฉพาะเสียง (mp3) ออกจากไฟล์วิดีโอ ถ้าล้มเหลวจะ fallback ใช้ไฟล์เดิม """
    audio_path = video_path.rsplit('.', 1)[0] + "_audio.mp3"

    try:
        print("🎵 Extracting audio to speed up AI... (MP3 Turbo Mode 🚀)")
        command = [
            'ffmpeg', '-y', '-i', video_path,
            '-vn',                  # ไม่เอาภาพ
            '-c:a', 'libmp3lame',
            '-b:a', '64k',
            '-ac', '1',             # mono ไฟล์เล็กลง เหมาะกับเสียงพูด
            '-threads', '0',
            audio_path
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,   # เก็บ error ไว้ดู
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        # เช็กทั้ง returncode และว่าไฟล์เกิดขึ้นจริงและไม่ว่างเปล่า
        if result.returncode != 0 or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            print(f"⚠️ ffmpeg failed (code {result.returncode}), fallback to original file")
            print(result.stderr[-1000:])  # แสดงท้าย log ของ ffmpeg
            return video_path

        return audio_path

    except FileNotFoundError:
        print("⚠️ ไม่พบ ffmpeg ในระบบ (ยังไม่ได้ติดตั้งหรือไม่อยู่ใน PATH) → ใช้ไฟล์เดิมแทน")
        return video_path
    except Exception as e:
        print(f"⚠️ Audio extraction failed, fallback to original video: {e}")
        return video_path

def extract_text_from_docx(file_path: str) -> str:
    """ สกัดข้อความจากไฟล์ Word (.docx) """
    try:
        doc = docx.Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs if para.text.strip() != ""])
        return text
    except Exception as e:
        print(f"❌ Error reading DOCX: {e}")
        return ""

def summarize_video(file_path: str, num_questions: int = 5, difficulty: str = "medium", generate_quiz: bool = False):
    try:
        # 🌟 เช็กนามสกุลไฟล์ว่าเป็นประเภทไหน
        ext = file_path.lower().rsplit('.', 1)[-1]
        is_document = ext in ['pdf', 'docx', 'doc', 'txt']
        
        # 🌟 เตรียมไฟล์ให้ AI ตามประเภท
        if ext == 'docx':
            print(f"📄 Extracting text from DOCX...")
            doc_text = extract_text_from_docx(file_path)
            content_for_ai = f"[Document Content]\n{doc_text}"
        else:
            audio_exts = ('mp3', 'm4a', 'wav', 'ogg', 'aac', 'flac')
            if ext not in audio_exts and ext != 'pdf' and "upload_" in os.path.basename(file_path):
                file_path = extract_audio_for_ai(file_path)

            print(f"📤 Uploading File: {file_path}")
            uploaded_file = genai.upload_file(path=file_path)
            
            while uploaded_file.state.name == "PROCESSING":
                print("⏳ Processing file on Google Server...")
                time.sleep(2)
                uploaded_file = genai.get_file(uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                return get_fallback_data("Google Server Process Failed")
                
            content_for_ai = uploaded_file

        print("✅ Analyzing content...")

        # 🌟 1. ปรับคำสั่งเวลา vs หน้าเอกสาร
        time_instruction = '{"time": "MM:SS", "text": "หัวข้อสั้น: รายละเอียด 2-3 ประโยคของช่วงเวลานี้"}'
        coverage_rule = "อย่างน้อย 1 จุดต่อทุก 1-2 นาทีของเนื้อหา"
        if is_document:
            time_instruction = '{"time": "หัวข้อ/หน้า", "text": "หัวข้อสั้น: รายละเอียด 2-3 ประโยคของหัวข้อนี้"}'
            coverage_rule = "อย่างน้อย 1 จุดต่อทุกหัวข้อหรือหน้าสำคัญ"

        # 🌟 2. โลจิกสวิตช์เปิด-ปิดการสร้างข้อสอบ (ฉบับลด Prompt ลดภาระ AI)
        diff_desc = {
            "easy": "เน้นนิยามพื้นฐาน",
            "medium": "เน้นความเข้าใจ",
            "hard": "เน้นประยุกต์ใช้"
        }.get(difficulty, "medium")

        if generate_quiz:
            quiz_instruction = 'ผสม "multiple_choice", "true_false", "short_answer"'
            quiz_rule = f"3. สร้างข้อสอบ {num_questions} ข้อ ระดับ: {difficulty} ({diff_desc})\n        4. รูปแบบ: {quiz_instruction}"
            quiz_json_structure = """
            "quizzes": [
                {
                    "id": "q1",
                    "type": "multiple_choice",
                    "question": "คำถาม?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer_index": 0,
                    "explanation": "อธิบายสั้นๆ 1 ประโยค"
                },
                {
                    "id": "q2",
                    "type": "true_false",
                    "question": "คำถาม?",
                    "correct_answer_index": 1,
                    "explanation": "อธิบายสั้นๆ 1 ประโยค"
                },
                {
                    "id": "q3",
                    "type": "short_answer",
                    "question": "คำถาม?",
                    "keywords": ["คีย์เวิร์ด"],
                    "suggested_answer": "แนวคำตอบ",
                    "explanation": "อธิบายสั้นๆ"
                }
            ]"""
            quiz_special_rule = f"2. สร้าง quizzes ให้ครบ {num_questions} ข้อ"
        else:
            quiz_rule = "3. ⚠️ ห้ามสร้างข้อสอบ (quizzes ให้เป็นอาร์เรย์ว่าง [])"
            quiz_json_structure = '            "quizzes": []'
            quiz_special_rule = '2. 🚫 บังคับ quizzes เป็น [] เท่านั้น'

        system_prompt = f"""
        คุณคือ AI ติวเตอร์และผู้ช่วยสรุปเนื้อหา
        เป้าหมาย: สรุปให้ถูกต้อง ครบถ้วน และครอบคลุมรายละเอียดทั้งหมด เพื่อให้ผู้เรียนใช้ทบทวนแทนการดูต้นฉบับซ้ำได้
        1. สรุปเนื้อหาให้ละเอียดที่สุด โดยดึงข้อมูลจากต้นฉบับ (คลิปหรือเอกสาร) โดยตรง (ให้ล้อตามโครงสร้างและประเด็นที่ผู้พูดสื่อสารจริงๆ)
        2. ใช้ Bullet Points (-) โดยแต่ละข้อต้องมีใจความครบในตัวเอง และห้ามข้ามเนื้อหาเพื่อให้สั้น
        {quiz_rule}
        """
        
        model = genai.GenerativeModel(
            model_name='gemini-flash-latest',
            system_instruction=system_prompt
        )
        
        prompt = f"""
        วิเคราะห์เนื้อหาและตอบเป็น JSON เท่านั้น โครงสร้างดังนี้:
        {{
           "speaker_info": "ชื่อผู้พูด/หัวข้อ",
            "summary_points": [
                {time_instruction} 
            ],
             "comprehensive_summary": "สรุปเนื้อหาทั้งหมดแบบละเอียดเป็น Markdown จัดรูปแบบด้วยหัวข้อ ### (ใช้ชื่อหัวข้อตามประเด็นที่มีในต้นฉบับจริงๆ) และใช้ Bullet Points อธิบายรายละเอียดให้ครบถ้วนตามเนื้อหา (ใช้ \\\\[ ... \\\\] สำหรับสูตรคณิตศาสตร์ถ้ามี)",
            "key_takeaways": "ใจความสำคัญ 3-5 ประโยค ครอบคลุมประเด็นหลักทั้งหมด",
            "flashcards": [
                {{
                    "front": "คำศัพท์/ประเด็นสำคัญ (ใช้ \\\\( ... \\\\))",
                    "back": "คำอธิบายความหมาย (ใช้ \\\\( ... \\\\))",
                    "type": "concept"
                }}
            ],
{quiz_json_structure}
        }}
        
        ข้อกำหนด:
        1. สร้าง Flashcards 5-8 ใบ (ดึงประเด็นสำคัญหรือคำศัพท์เด่นๆ จากต้นฉบับ)
        - ความครอบคลุม: summary_points ต้องไล่ตามลำดับเนื้อหาตั้งแต่ต้นจนจบ {coverage_rule} แต่ละจุดมีหัวข้อสั้นนำหน้า ตามด้วยรายละเอียด 2-3 ประโยค
        - ความถูกต้อง: ใช้เฉพาะข้อมูลที่มีในเนื้อหา ห้ามแต่งหรือเดาเพิ่มเด็ดขาด หากส่วนใดฟังไม่ชัดให้ระบุว่าไม่ชัดเจน
        {quiz_special_rule}
        3. ⚠️ JSON ESCAPE RULE: สูตร LaTeX บังคับใช้ Backslash สองตัว (\\\\) เสมอ (เช่น \\\\frac)
        """

        safety_settings = [
            {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
            {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
            {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
            {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
        ]

        # 🚀 เพิ่ม Retry Logic รับมือ 503 (Server Overload) / 429 (Quota)
        MAX_RETRIES = 3
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                response = model.generate_content(
                    [content_for_ai, prompt],
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                        "top_p": 0.8
                    },
                    safety_settings=safety_settings,
                    request_options={"timeout": 600},
                    stream=True
                )

                full_text = ""
                for chunk in response:
                    if chunk.text:
                        full_text += chunk.text

                if getattr(response, 'prompt_feedback', None) and response.prompt_feedback.block_reason:
                    return get_fallback_data("Content blocked due to Safety Filter.")

                return clean_json_response(full_text)

            except Exception as e:
                last_exception = e
                error_str = str(e)
                
                # แยกระหว่าง 503 (เซิร์ฟเวอร์เต็มชั่วคราว) กับ 429 (โควต้าของเราเต็ม)
                is_503 = "503" in error_str or "overloaded" in error_str.lower()
                is_429 = "429" in error_str or "quota" in error_str.lower()

                if (is_503 or is_429) and attempt < MAX_RETRIES - 1:
                    # ถ้าโควต้าเต็ม (429) บังคับรอ 62 วินาทีเพื่อให้ชัวร์ว่าพ้นระยะแบน
                    # ถ้าแค่เซิร์ฟเวอร์โหลดหนัก (503) ให้รอแค่ 10 วินาที
                    wait_time = 62 if is_429 else 10
                    print(f"⚠️ AI Busy ({'Quota 429 Limit' if is_429 else 'Server 503'}) - Retrying in {wait_time}s... (Attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ General Error: {e}")
                    return get_fallback_data("⏳ AI limits reached (Free Tier). Please wait 1 minute and click analyze again.")

    except Exception as e:
        error_str = str(e)
        # (ส่วนจัดการ Error เดิมของคุณปอนด์)
        friendly_error = "An error occurred during processing. Please try again."
        if "429" in error_str or "quota" in error_str.lower():
            friendly_error = "⏳ AI system is currently overloaded (Quota limit). Please wait 1-2 minutes and try again."
        elif "503" in error_str:
            friendly_error = "🔥 Google AI servers are overloaded. Please try again later."
        
        print(f"❌ General Error: {error_str}")
        return get_fallback_data(friendly_error)

# ==========================================
# 🤖 ฟังก์ชัน AI Tutor (แบบ Streaming)
# ==========================================
def ask_ai_tutor_stream(message: str, context: str):
    """สมองกลของ Chatbot ไว้ตอบคำถามแบบสายน้ำ (พิมพ์ทีละตัว)"""
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        prompt = f"""
        คุณคือ "AI Tutor" ผู้ช่วยตอบคำถามที่อธิบายเข้าใจง่าย
        หน้าที่ของคุณคือตอบคำถาม โดยอิงจากเนื้อหาบทเรียนที่ให้มานี้เป็นหลัก:
        
        [เนื้อหาบทเรียน]
        {context}

        คำถาม: {message}

        ข้อบังคับ:
        1. ตอบให้ตรงประเด็น อธิบายให้เข้าใจง่าย
        2. ถ้าคำถามไม่อยู่ในเนื้อหาบทเรียน ให้ตอบจากข้อมูลทั่วไป
        3. ภาษา: ใช้ภาษาตามคำถาม
        """

        # 🌟 สั่งให้ AI ส่งข้อมูลกลับมาทีละก้อน (stream=True)
        response = model.generate_content(prompt, stream=True)
        for chunk in response:
            if chunk.text:
                yield chunk.text

    except Exception as e:
        print(f"❌ Chatbot Error: {e}")
        yield "Error: Connection lost. Please ask again."

# ==========================================
# ➕ ระบบ Generate More Quiz (บังคับเฉพาะ Multiple Choice)
# ==========================================
def generate_quizzes_only(context_text, num_questions, difficulty, include_written=True):
    model = genai.GenerativeModel('gemini-flash-latest') 
    
    quiz_instruction = 'รูปแบบ "multiple_choice" (เลือกตอบ 4 ตัวเลือก) เท่านั้น ห้ามสร้างแบบ True/False หรือข้อเขียนเด็ดขาด'
    
    diff_desc = {
        "easy": "เน้นนิยาม ความหมายพื้นฐาน",
        "medium": "เน้นความเข้าใจและการเชื่อมโยงประเด็น",
        "hard": "เน้นการวิเคราะห์และการประยุกต์ใช้ขั้นสูง"
    }.get(difficulty, "medium")

    # 🌟 อัปเกรด Prompt: บังคับ AI ให้ใช้ \\ เสมอ (ป้องกัน JSON พัง)
    prompt = f"""
    คุณคือคุณครูผู้เชี่ยวชาญ จงสร้างแบบทดสอบ {num_questions} ข้อ (โหมดความเร็วสูง)
    ระดับความยาก: {difficulty} ({diff_desc})
    ประเภทข้อสอบ: {quiz_instruction}
    
    กฎเหล็กเพื่อความเร็วและกันระบบพัง (สำคัญมาก):
    1. คำถามและตัวเลือก ให้เขียนสั้น กระชับ ได้ใจความ
    2. explanation (คำอธิบายเฉลย) ห้ามยาวเกิน 1 ประโยคเด็ดขาด
    3. ⚠️ JSON ESCAPE RULE: หากมีสูตรคณิตศาสตร์ หรือสัญลักษณ์ LaTeX ต้องใช้เครื่องหมาย Backslash สองตัว (\\\\) เสมอ!
       - ห้ามใช้ตัวเดียว: \\( \\frac{{1}}{{2}} \\) หรือ \\sin หรือ \\theta
       - บังคับใช้สองตัว: \\\\( \\\\frac{{1}}{{2}} \\\\) หรือ \\\\sin หรือ \\\\theta
       ถ้าไม่ทำตาม ระบบ JSON จะพังทันที!
    
    ตอบกลับเป็น JSON เท่านั้น โดยต้องใช้โครงสร้างตามตัวอย่างด้านล่างนี้เป๊ะๆ:
    {{
      "quizzes": [
        {{
          "id": "gen_mcq_1",
          "type": "multiple_choice",
          "question": "ผลลัพธ์ของสมการ \\\\( \\\\sum F = 0 \\\\) คือข้อใด?",
          "options": ["A", "B", "C", "D"],
          "correct_answer_index": 0,
          "explanation": "อธิบายสั้นๆ ห้ามยาวเกิน 1 ประโยค"
        }}
      ]
    }}

    Study Guide Context:
    {context_text[:5000]}
    """
    
    # 🚀 เพิ่ม Retry Logic รับมือ 503 (Server Overload) / 429 (Quota)
    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            if not response or not response.text:
                return []

            raw_text = response.text.strip()

            # 🌟 เอาท่าไม้ตายมาวางดักไว้ตรงนี้ด้วยครับ (เขียนแบบรวบรัดบรรทัดเดียว)
            raw_text = raw_text.replace('\\\\', '__DBL__').replace('\\"', '__QOT__').replace('\\n', '__NL__').replace('\\t', '__TAB__').replace('\\r', '__CR__')
            raw_text = raw_text.replace('\\', '\\\\')
            raw_text = raw_text.replace('__DBL__', '\\\\').replace('__QOT__', '\\"').replace('__NL__', '\\n').replace('__TAB__', '\\t').replace('__CR__', '\\r')

            data = json.loads(raw_text)
            return data.get("quizzes", [])

        except Exception as e:
            error_str = str(e)
            is_retryable = "503" in error_str or "overloaded" in error_str.lower() or "429" in error_str

            if is_retryable and attempt < MAX_RETRIES - 1:
                wait_time = (attempt + 1) * 5  # รอ 5, 10, 15 วินาที
                print(f"⚠️ Quiz Gen overloaded (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Quiz Gen Error: {e}")
                return []