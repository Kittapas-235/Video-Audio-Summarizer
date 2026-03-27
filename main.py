import uvicorn
import yt_dlp
import uuid
import shutil
import os
import time
import re
import mimetypes
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from services.ai_engine import summarize_video, ask_ai_tutor
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel

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

def cleanup_old_files():
    now = time.time()
    one_day_ago = now - (24 * 60 * 60)
    for f in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, f)
        if os.path.isfile(file_path) and os.stat(file_path).st_mtime < one_day_ago:
            try:
                os.remove(file_path)
            except:
                pass

# สร้าง Scheduler ไว้ด้านบนแต่ยังไม่สั่ง start จนกว่าจะถึง main
scheduler = BackgroundScheduler()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

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
        return HTMLResponse(status_code=404, content="Video not found")

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
    num_questions: int = Form(5), 
    difficulty: str = Form("medium"),
    include_written: bool = Form(False)
):
    try:
        # 1. เช็กประเภทไฟล์เบื้องต้น (Security)
        if not file.content_type.startswith("video/") and not file.content_type.startswith("audio/"):
            return templates.TemplateResponse(request=request, name="index.html", context={
                "request": request, "error_msg": "❌ Invalid file type. Only Audio or Video allowed."
            })

        file_ext = os.path.splitext(file.filename)[1].lower() or ".mp4"
        filename = f"upload_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        # 2. เขียนไฟล์แบบ Chunk (ทยอยเขียนทีละนิด ไม่ให้ RAM พัง) พร้อมนับขนาดไฟล์
        file_size = 0
        with open(file_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024) # อ่านทีละ 1 MB
                if not chunk:
                    break
                file_size += len(chunk)
                
                # ถ้าขนาดเกิน 500 MB ให้หยุดทันที ลบไฟล์ทิ้ง และเด้ง Error
                if file_size > MAX_FILE_SIZE:
                    buffer.close()
                    os.remove(file_path) # ลบไฟล์ที่โหลดค้างไว้ทิ้งซะ
                    return templates.TemplateResponse(request=request, name="index.html", context={
                        "request": request, "error_msg": "❌ File is too large. Maximum size is 500MB."
                    })
                
                buffer.write(chunk)

        audio_extensions = ['.mp3', '.m4a', '.wav', '.ogg', '.aac', '.flac']
        is_audio = file_ext in audio_extensions

        ai_data = summarize_video(file_path, num_questions, difficulty, include_written)

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

# --- YouTube URL ---
@app.post("/process-url")
async def process_url(
    request: Request, 
    video_url: str = Form(...),
    num_questions: int = Form(5), 
    difficulty: str = Form("medium"),
    include_written: bool = Form(False)
):
    try:
        # 🛡️ เช็กความปลอดภัย: ต้องเป็น URL ของ YouTube เท่านั้น
        if not re.match(r"^(https?\:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$", video_url):
            return templates.TemplateResponse(request=request, name="index.html", context={
                "request": request, 
                "error_msg": "❌ Please provide a valid YouTube URL."
            })

        yt_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", video_url)
        youtube_id = yt_id_match.group(1) if yt_id_match else ""
        
        filename = f"web_{uuid.uuid4().hex}.m4a"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        ydl_opts = {
            'format': '140/bestaudio[ext=m4a]/best',
            'outtmpl': file_path,
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        ai_data = summarize_video(file_path, num_questions, difficulty, include_written)

        return templates.TemplateResponse(request=request, name="player.html", context={
            "request": request, 
            "is_youtube": True,
            "youtube_id": youtube_id,
            "video_filename": filename, 
            "data": ai_data,
            "filename": "YouTube Video"
        })
    except Exception as e:
        print(f"❌ Error in process-url: {e}")
        return templates.TemplateResponse(request=request, name="index.html", context={
            "request": request, 
            "error_msg": "Cannot access this YouTube video. It might be private, deleted, or restricted."
        })
# ==========================================
# 🤖 ระบบ AI Chatbot Tutor
# ==========================================
class ChatRequest(BaseModel):
    message: str
    context: str

@app.post("/chat")
def chat_with_ai(request: ChatRequest):
    answer = ask_ai_tutor(request.message, request.context)
    return {"answer": answer}

# ==========================================
# ➕ ระบบ Generate More Quiz
# ==========================================
class GenQuizRequest(BaseModel):
    video_filename: str
    num_questions: int
    difficulty: str

@app.post("/generate-more-quiz")
def generate_more_quiz(request: GenQuizRequest):
    file_path = os.path.join(UPLOAD_DIR, request.video_filename)
    new_data = summarize_video(file_path, request.num_questions, request.difficulty)
    return {"quizzes": new_data.get("quizzes", [])}

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