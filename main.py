import uvicorn
import yt_dlp
import uuid
import shutil
import os
import time
import re
import mimetypes
import sqlite3
import json
import hashlib
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, UploadFile, File, Form, Response, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

# 🔐 โมดูลสำหรับระบบ Login & Security ที่เราเพิ่งโหลดมา
from passlib.context import CryptContext
from jose import JWTError, jwt

from services.ai_engine import summarize_video, ask_ai_tutor_stream, generate_quizzes_only

app = FastAPI()

# --- การตั้งค่าเส้นทาง ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "temp_uploads")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

@app.get("/logo.png")
async def logo():
    return FileResponse("logo.png")

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("favicon.ico")

@app.get("/cortisol.gif")
async def get_gif():
    return FileResponse("cortisol.gif")

# ⏳ เก็บไฟล์ที่อัปโหลดไว้กี่ชั่วโมงก่อนลบ (ปรับได้ตามพื้นที่ดิสก์)
FILE_RETENTION_HOURS = 24 * 7

def cleanup_old_files():
    now = time.time()
    cutoff = now - (FILE_RETENTION_HOURS * 60 * 60)
    for f in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, f)
        if os.path.isfile(file_path) and os.stat(file_path).st_mtime < cutoff:
            try:
                os.remove(file_path)
            except:
                pass

# ==========================================
# 🔐 การตั้งค่าความปลอดภัย (Security Settings)
# ==========================================
SECRET_KEY = "VA_SUMMAR_SUPER_SECRET_KEY" # ในอนาคตควรย้ายไปไว้ในไฟล์ .env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # ล็อกอินค้างไว้ได้ 7 วัน

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# ---------- 📋 เงื่อนไขชื่อผู้ใช้/รหัสผ่านตอนสมัคร (มาตรฐานทั่วไป) ----------
def validate_username(name: str):
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,20}", name):
        return "Username must be 3-20 characters: English letters, numbers, . _ - only (no spaces)."
    return None

def validate_password(pw: str):
    if not re.fullmatch(r"[A-Za-z0-9]+", pw):
        return "Password must contain English letters and numbers."
    if not re.search(r"[A-Za-z]", pw):
        return "Password must include at least one English letter."
    if not (8 <= len(pw) <= 64):
        return "Password must be 8-64 characters."
    if not re.search(r"[0-9]", pw):
        return "Password must include a number (0-9)."
    return None

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ฟังก์ชันอ่าน Cookie เพื่อดูว่าใครล็อกอินอยู่
def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        # ตัดคำว่า "Bearer " ออก
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None

# ==========================================
# 🗄️ อัปเดตระบบฐานข้อมูล SQLite (เพิ่มตาราง Users)
# ==========================================
DB_FILE = "va_summar.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 1. ตารางผู้ใช้งาน
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    # 2. ตาราง Cache (เพิ่มคอลัมน์ username เพื่อแยกประวัติของแต่ละคน)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_cache (
            id TEXT,
            username TEXT,
            source_type TEXT,
            difficulty TEXT,
            has_quiz BOOLEAN,
            ai_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, username)
        )
    ''')
    # 🆕 migrate: เพิ่มคอลัมน์เก็บชื่อไฟล์ที่อัปโหลด (ฐานข้อมูลเดิมไม่มี)
    for col in ("video_filename", "original_filename"):
        try:
            cursor.execute(f"ALTER TABLE video_cache ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass  # มีคอลัมน์นี้อยู่แล้ว
    conn.commit()
    conn.close()

init_db()

# สร้าง Scheduler ไว้ด้านบนแต่ยังไม่สั่ง start จนกว่าจะถึง main
scheduler = BackgroundScheduler()

# ฟังก์ชันดึงประวัติของ User คนที่ล็อกอินอยู่
def get_all_history(username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, source_type, difficulty, created_at, ai_data FROM video_cache WHERE username=? ORDER BY created_at DESC LIMIT 20",
        (username,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    history_list = []
    for row in rows:
        item_id, source_type, difficulty, created_at, ai_data_str = row
        ai_data = json.loads(ai_data_str)
        speaker = ai_data.get("speaker_info", "Unknown Topic")
        
        history_list.append({
            "id": item_id,
            "type": source_type,
            "difficulty": difficulty,
            "date": created_at,
            "speaker": speaker
        })
    return history_list

# โฮมเพจ (เวอร์ชันดึงประวัติ และเช็กคนล็อกอิน)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    username = get_current_user(request)
    history_data = []
    
    # ถ้าล็อกอินแล้ว ให้ดึงประวัติของคนๆ นั้นออกมา
    if username:
        history_data = get_all_history(username)
        
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request, 
        "history": history_data,
        "username": username # ส่ง username ไปให้หน้าเว็บรู้ด้วย
    })

# ดึงข้อมูลจาก Cache (เวอร์ชันมี username)
def get_cache(username, unique_id, difficulty, has_quiz):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ai_data FROM video_cache WHERE id=? AND username=? AND difficulty=? AND has_quiz=?",
        (unique_id, username, difficulty, has_quiz)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

# บันทึกข้อมูลลง Cache (เวอร์ชันมี username)
def save_cache(username, unique_id, source_type, difficulty, has_quiz, ai_data, video_filename=None, original_filename=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    ai_data_json = json.dumps(ai_data, ensure_ascii=False)
    cursor.execute(
        "INSERT OR REPLACE INTO video_cache (id, username, source_type, difficulty, has_quiz, ai_data, video_filename, original_filename) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (unique_id, username, source_type, difficulty, has_quiz, ai_data_json, video_filename, original_filename)
    )
    conn.commit()
    conn.close()

# อัปเดตชื่อไฟล์ล่าสุดของประวัติเดิม (ใช้ตอนอัปโหลดไฟล์เดิมซ้ำแล้วเจอ Cache)
def update_cache_file(username, unique_id, video_filename, original_filename):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE video_cache SET video_filename=?, original_filename=? WHERE id=? AND username=?",
        (video_filename, original_filename, unique_id, username)
    )
    conn.commit()
    conn.close()

# ==========================================
# 🚪 ระบบเข้าสู่ระบบและสมัครสมาชิก
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    error = validate_username(username) or validate_password(password)
    if error:
        return templates.TemplateResponse("register.html", {"request": request, "error_msg": error})

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        hashed_pw = get_password_hash(password)
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed_pw))
        conn.commit()
        # สมัครเสร็จ เด้งไปหน้า login
        return templates.TemplateResponse("login.html", {"request": request, "success_msg": "Account created successfully! Please login."})
    except sqlite3.IntegrityError:
        # ดักจับกรณีชื่อผู้ใช้ซ้ำ
        return templates.TemplateResponse("register.html", {"request": request, "error_msg": "Username already exists."})
    finally:
        conn.close()

@app.post("/login")
async def login_user(response: Response, request: Request, username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(password, row[0]):
        return templates.TemplateResponse("login.html", {"request": request, "error_msg": "Invalid username or password"})

    # สร้าง Token ปลอดภัย
    access_token = create_access_token(data={"sub": username})
    
    # สร้าง Redirect กลับไปหน้าแรก พร้อมกับฝัง Cookie
    redirect_response = Response(status_code=302)
    redirect_response.headers["Location"] = "/"
    redirect_response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True, # ป้องกัน XSS Attack
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return redirect_response

@app.get("/logout")
async def logout():
    response = Response(status_code=302)
    response.headers["Location"] = "/login"
    response.delete_cookie("access_token")
    return response

# ==========================================
# 🚀 ระบบ Streaming Video
# ==========================================
def iterfile(file_path, start, end, chunk_size=1024*1024):
    with open(file_path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data

@app.get("/stream-video/{filename}")
async def stream_video(filename: str, request: Request):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        return HTMLResponse(status_code=404, content="File not found")

    # 🌟 เพิ่มบล็อกนี้: ถ้าเป็นไฟล์เอกสาร ให้ใช้ FileResponse ส่งไปรวดเดียวเลย
    # (ถ้าใช้ Streaming แบบวิดีโอ เบราว์เซอร์จะงงและเปิด PDF ใน iframe ไม่ได้)
    if filename.endswith(('.pdf', '.docx', '.txt')):
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "application/pdf" if filename.endswith('.pdf') else "application/octet-stream"
        return FileResponse(file_path, media_type=content_type)

    # --- โค้ดส่วนจัดการ Streaming วิดีโอ (ปล่อยไว้เหมือนเดิม) ---
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range")

    if range_header:
        byte_range = range_header.strip().replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
    else:
        start = 0
        end = file_size - 1

    content_length = end - start + 1
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "video/mp4"

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": content_type,
    }

    return StreamingResponse(iterfile(file_path, start, end), status_code=206, headers=headers)

# --- อัปโหลดไฟล์ ---
MAX_FILE_SIZE = 500 * 1024 * 1024 # ตั้งลิมิตไว้ที่ 500 MB (ปรับเพิ่มเป็น 1024 สำหรับ 1GB ได้ครับ)

@app.post("/process-file")
async def process_file(
    request: Request, 
    file: UploadFile = File(...),
    difficulty: str = Form("medium"),
    generate_quiz: bool = Form(False)
):
    try:
        # 🚨 เพิ่มโค้ดบังคับเช็ก Login ตรงนี้!
        username = get_current_user(request)
        if not username:
            return templates.TemplateResponse(request=request, name="login.html", context={
                "request": request, "error_msg": "กรุณาเข้าสู่ระบบก่อนอัปโหลดไฟล์"
            })

        # 1. รับนามสกุลไฟล์
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        # 2. เตรียมชื่อไฟล์ชั่วคราว
        filename = f"upload_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        # 3. 🌟 (ย้ายขึ้นมา) อ่านไฟล์ทีละนิด พร้อมสร้างรหัส Hash (file_unique_id) ให้เสร็จก่อน
        file_size = 0
        md5_hash = hashlib.md5() 
        with open(file_path, "wb") as buffer:
            chunk_size = 10 * 1024 * 1024 
            while True:
                chunk = await file.read(chunk_size) 
                if not chunk: break
                md5_hash.update(chunk)
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    buffer.close()
                    os.remove(file_path)
                    return templates.TemplateResponse(...)
                buffer.write(chunk)

        # ตัวแปรนี้จะพร้อมใช้งานแล้ว
        file_unique_id = md5_hash.hexdigest() 

        audio_extensions = ['.mp3', '.m4a', '.wav', '.ogg', '.aac', '.flac']
        is_audio = file_ext in audio_extensions

        # 🌟 ระบบ CACHING: เช็กฐานข้อมูลก่อนเรียก AI (เพิ่ม username)
        cached_data = get_cache(username, file_unique_id, difficulty, generate_quiz)
        
        if cached_data:
            print(f"⚡ FAST TRACK: ดึงข้อมูลจาก Cache สำหรับไฟล์ {file.filename}")
            ai_data = cached_data
            # ผูกไฟล์ที่เพิ่งอัปโหลดเข้ากับประวัติเดิม เพื่อให้เปิดดูวิดีโอจาก My Library ได้
            update_cache_file(username, file_unique_id, filename, file.filename)
        else:
            print(f"🧠 ประมวลผลใหม่ด้วย AI สำหรับไฟล์ {file.filename}")
            ai_data = await run_in_threadpool(summarize_video, file_path, 5, difficulty, generate_quiz)
            
            # บันทึกผลลัพธ์ลง Cache (เพิ่ม username)
            save_cache(username, file_unique_id, "file", difficulty, generate_quiz, ai_data, filename, file.filename)

        return templates.TemplateResponse(request=request, name="player.html", context={
            "request": request,
            "is_youtube": False,
            "is_audio": is_audio,
            "youtube_id": "",
            "video_filename": filename, 
            "data": ai_data,
            "filename": file.filename
        })
    except Exception as e:
        print(f"❌ Error in process-file: {e}")
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request,
            "error_msg": f"An error occurred while processing the file: {str(e)}"
        })

# --- YouTube URL (เวอร์ชันรวมระบบ Caching + แก้ Error หาไฟล์ไม่เจอ) ---
@app.post("/process-url")
def process_url(
    request: Request, 
    video_url: str = Form(...),
    difficulty: str = Form("medium"),
    generate_quiz: bool = Form(False)
):
    try:
        # 🚨 เพิ่มโค้ดบังคับเช็ก Login
        username = get_current_user(request)
        if not username:
            return templates.TemplateResponse(request=request, name="login.html", context={
                "request": request, "error_msg": "กรุณาเข้าสู่ระบบก่อนสรุปวิดีโอ YouTube"
            })

        # 🛡️ เช็กความปลอดภัย: ต้องเป็น URL ของ YouTube เท่านั้น
        if not re.match(r"^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$", video_url):
            return templates.TemplateResponse(request=request, name="index.html", context={
                "request": request, 
                "error_msg": "❌ Please provide a valid YouTube URL."
            })

        yt_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", video_url)
        youtube_id = yt_id_match.group(1) if yt_id_match else ""
        
        # ==========================================
        # 🌟 สเต็ปที่ 1: เช็ก Cache จากฐานข้อมูลก่อนโหลดคลิป!
        # ==========================================
        if youtube_id:
            cached_data = get_cache(username, youtube_id, difficulty, generate_quiz)
            if cached_data:
                print(f"⚡ FAST TRACK: ดึงข้อมูลจาก Cache สำหรับคลิป {youtube_id}")
                return templates.TemplateResponse(request=request, name="player.html", context={
                    "request": request, 
                    "is_youtube": True,
                    "youtube_id": youtube_id,
                    "video_filename": "", # ดึงวิดีโอจาก YouTube ฝั่ง Frontend ได้เลย
                    "data": cached_data,
                    "filename": "YouTube Video (Cached)"
                })

        # ==========================================
        # 🔽 ถ้าไม่มีใน Cache ให้ทำงานตามปกติ (ดาวน์โหลด -> AI)
        # ==========================================
        
        # 1. เปลี่ยนนามสกุลไฟล์เป็น .mp3
        base_filename = f"web_{uuid.uuid4().hex}"
        final_filename = f"{base_filename}.mp3" 
        final_file_path = os.path.join(UPLOAD_DIR, final_filename)
        
        cookie_path = "cookies.txt"
        if os.path.exists("/etc/secrets/cookies.txt"):
            cookie_path = "/etc/secrets/cookies.txt"

        # 2. เพิ่มคำสั่ง Postprocessor ให้แปลงเป็น mp3 ชัวร์ๆ
        ydl_opts = {
            'format': 'bestaudio/best', 
            'postprocessors': [{ 
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'outtmpl': os.path.join(UPLOAD_DIR, f"{base_filename}.%(ext)s"),
            'noplaylist': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            }
        }
        
        if os.path.exists(cookie_path):
            ydl_opts['cookiefile'] = cookie_path

        # ดาวน์โหลดไฟล์
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # 3. เช็กให้ชัวร์ว่าไฟล์มันสร้างเสร็จแล้วจริงๆ 
        retry = 0
        while not os.path.exists(final_file_path) and retry < 5:
            time.sleep(1)
            retry += 1

        if not os.path.exists(final_file_path):
            raise FileNotFoundError(f"ไม่พบไฟล์: {final_file_path} (yt-dlp อาจมีปัญหา)")

        # 4. ส่งให้ AI ประมวลผล
        ai_data = summarize_video(final_file_path, 5, difficulty, generate_quiz)

        # 🌟 สเต็ปที่ 2: บันทึกผลลัพธ์ลง Cache (เซฟเฉพาะตอนที่ AI ตอบกลับมาสำเร็จ)
        if youtube_id and ai_data:
            save_cache(username, youtube_id, "youtube", difficulty, generate_quiz, ai_data)
            print(f"💾 SAVED TO CACHE: บันทึกข้อมูลคลิป {youtube_id} เรียบร้อยแล้ว")

        return templates.TemplateResponse(request=request, name="player.html", context={
            "request": request, 
            "is_youtube": True,
            "youtube_id": youtube_id,
            "video_filename": final_filename, 
            "data": ai_data,
            "filename": "YouTube Video"
        })

    except Exception as e:
        print(f"❌ Error in process-url: {e}")
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request, 
            "error_msg": f"ไม่สามารถดึงข้อมูล YouTube ได้: {str(e)}"
        })

# ==========================================
# 🤖 ระบบ AI Chatbot Tutor (รับ-ส่งแบบสายน้ำ)
# ==========================================
class ChatRequest(BaseModel):
    message: str
    context: str

@app.post("/chat")
def chat_with_ai(request: ChatRequest):
    # 🌟 ห่อหุ้มฟังก์ชันด้วย StreamingResponse เพื่อปล่อยข้อความไหลไปหน้าเว็บ
    return StreamingResponse(
        ask_ai_tutor_stream(request.message, request.context), 
        media_type="text/plain"
    )

# ==========================================
# ➕ ระบบ Generate More Quiz
# ==========================================
class GenQuizRequest(BaseModel):
    context: str  
    num_questions: int
    difficulty: str

@app.post("/generate-more-quiz")
def generate_more_quiz(request: GenQuizRequest):
    new_quizzes = generate_quizzes_only(request.context, request.num_questions, request.difficulty)
    return {"quizzes": new_quizzes or []}

# ==========================================
# 🔌 ระบบรับข้อมูลจาก Browser Extension
# ==========================================
@app.get("/process-extension", response_class=HTMLResponse)
async def process_extension(request: Request, url: str):
    # สร้างหน้าเว็บจำลองขึ้นมา เพื่อแปลงลิงก์ที่รับมา (GET) ให้เป็นฟอร์ม (POST) ส่งให้ระบบหลัก
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Loading VA-Summar...</title>
        <style>
            body {{
                background-color: #1a1a1a;
                color: white;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .loader {{
                border: 4px solid #333;
                border-top: 4px solid #00d2ff;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin-bottom: 20px;
            }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="loader"></div>
        <h3>Connecting to VA-Summar...</h3>
        <p style="color: #888;">Please wait, auto-forwarding video URL</p>
        
        <!-- ฟอร์มล่องหนสำหรับยิงข้อมูลเข้าหลังบ้าน -->
        <form id="autoSubmitForm" action="/process-url" method="post" style="display: none;">
            <input type="hidden" name="video_url" value="{url}">
            <input type="hidden" name="difficulty" value="medium">
            <input type="hidden" name="generate_quiz" value="true">
        </form>
        
        <script>
            // สั่งให้ฟอร์มกดยืนยันตัวเอง (Submit) ทันทีที่โหลดหน้าเว็บเสร็จ
            window.onload = function() {{
                document.getElementById('autoSubmitForm').submit();
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ==========================================
# ⏱️ ระบบดูประวัติย้อนหลัง (History)
# ==========================================
@app.get("/history/{item_id}")
async def view_history(request: Request, item_id: str): # 🌟 แก้เป็น str และเอา Depends ออก
    username = get_current_user(request)
    if not username:
        return RedirectResponse(url="/login", status_code=302)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # เช็กว่าประวัตินี้เป็นของคนที่กำลังล็อกอินอยู่จริงๆ
    cursor.execute("SELECT source_type, difficulty, has_quiz, ai_data, video_filename, original_filename FROM video_cache WHERE id=? AND username=?", (item_id, username))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request, 
            "error_msg": "❌ ไม่พบข้อมูลประวัติการสรุปนี้ หรือคุณไม่มีสิทธิ์เข้าถึง"
        })
        
    source_type, difficulty, has_quiz, ai_data_str, saved_filename, original_filename = row
    ai_data = json.loads(ai_data_str)

    # 🌟 เช็กประเภทจาก source_type ในฐานข้อมูล
    is_yt = (source_type == "youtube")
    
    # 🌟 ถ้าเป็น YouTube ให้ใช้ item_id เป็น youtube_id 
    yt_id = item_id if is_yt else ""
    
    # สำหรับไฟล์ที่อัปโหลด (ปกติถ้าเกิน 1 วันไฟล์จะโดนลบ เราส่งค่าว่างไปให้ขึ้น Video Expired ถูกต้องแล้วครับ)
    vid_file = ""
    if not is_yt and saved_filename:
        saved_filename = os.path.basename(saved_filename)
        if os.path.isfile(os.path.join(UPLOAD_DIR, saved_filename)):
            vid_file = saved_filename  # ไฟล์ยังอยู่ ให้เล่นได้ ถ้าถูกลบแล้วจะขึ้น Video Expired ตามเดิม

    return templates.TemplateResponse("player.html", {
        "request": request,
        "data": ai_data,
        "is_youtube": is_yt,
        "youtube_id": yt_id,
        "video_filename": vid_file,
        "is_audio": os.path.splitext(vid_file)[1].lower() in ['.mp3', '.m4a', '.wav', '.ogg', '.aac', '.flac'],
        "filename": original_filename or ""
    })

# ==========================================
# 🗑️ ระบบลบประวัติ (Delete History)
# ==========================================
@app.delete("/history/{item_id}")
async def delete_history(request: Request, item_id: str):
    username = get_current_user(request)
    if not username:
        return {"success": False, "message": "Unauthorized"}

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # ลบข้อมูลที่ตรงกับ id และ username ของคนที่ล็อกอินเท่านั้น
        cursor.execute("DELETE FROM video_cache WHERE id=? AND username=?", (item_id, username))
        
        if cursor.rowcount > 0:
            conn.commit()
            conn.close()
            return {"success": True, "message": "Deleted successfully"}
        else:
            conn.close()
            return {"success": False, "message": "Item not found or unauthorized"}
            
    except Exception as e:
        print(f"Delete error: {e}")
        return {"success": False, "message": str(e)}

# ==========================================
# 🏁 Main Entry Point
# ==========================================
if __name__ == "__main__":
    # เริ่ม Scheduler
    scheduler.add_job(cleanup_old_files, 'interval', hours=24)
    scheduler.start()
    cleanup_old_files()

    # รันเซิร์ฟเวอร์
    print("🚀 Starting LectureLens Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)