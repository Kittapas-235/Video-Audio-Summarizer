import uvicorn
import yt_dlp
import uuid
import shutil
import os
import time
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from services.ai_engine import summarize_video
from apscheduler.schedulers.background import BackgroundScheduler
import imageio_ffmpeg

app = FastAPI()

# --- การตั้งค่าเส้นทาง ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "temp_uploads")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# เชื่อมต่อไฟล์ static เพื่อให้เข้าถึงวิดีโอได้
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

# --- ระบบลบไฟล์เก่าอัตโนมัติ (Cleanup) ---
def cleanup_old_files():
    now = time.time()
    one_week_ago = now - (7 * 24 * 60 * 60) # 1 สัปดาห์
    for f in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, f)
        if os.path.isfile(file_path) and os.stat(file_path).st_mtime < one_week_ago:
            os.remove(file_path)
            print(f"🗑️ ลบไฟล์เก่า: {f}")

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_old_files, 'interval', hours=24)
scheduler.start()

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "title": "LectureLens AI"
    })

# --- File Loader ---
@app.post("/process-file", response_class=HTMLResponse)
async def process_file(
    request: Request, 
    file: UploadFile = File(...),
    num_questions: int = Form(5), 
    difficulty: str = Form("medium")
):
    try:
        file_ext = os.path.splitext(file.filename)[1] or ".mp4"
        filename = f"upload_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # ส่งค่าจำนวนข้อและความยากไปประมวลผล
        ai_data = summarize_video(file_path, num_questions, difficulty)

        return templates.TemplateResponse("player.html", {
            "request": request,
            "video_url": f"/static/{filename}",
            "data": ai_data
        })
    except Exception as e:
        print(f"❌ Error: {e}")
        return HTMLResponse(content=f"<h3>เกิดข้อผิดพลาด: {str(e)}</h3>", status_code=500)
# --- 
@app.post("/process-url", response_class=HTMLResponse)
async def process_url(
    request: Request, 
    video_url: str = Form(...),
    num_questions: int = Form(5), 
    difficulty: str = Form("medium")
):
    filename = f"web_{uuid.uuid4().hex}.mp4"
    file_path = os.path.join(UPLOAD_DIR, filename)
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', # โหลดภาพและเสียงที่ดีที่สุดมาประกอบร่างกัน
        'outtmpl': file_path,
        'noplaylist': True,
        'cookiefile': 'cookies.txt',
        'ffmpeg_location': ffmpeg_path  # 👈 ชี้เป้าให้ yt-dlp เรียกใช้ ffmpeg ในการประกอบร่าง
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        ai_data = summarize_video(file_path, num_questions, difficulty)
    
        return templates.TemplateResponse("player.html", {
            "request": request, 
            "video_url": f"/static/{filename}", 
            "data": ai_data
        })
    except Exception as e:
        return HTMLResponse(content=f"<h3>เกิดข้อผิดพลาด: {str(e)}</h3>", status_code=500)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)