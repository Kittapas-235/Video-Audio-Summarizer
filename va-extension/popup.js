// ⚙️ ที่อยู่ของเว็บแอป Lila (ตอนนี้เป็นเครื่องตัวเอง เปลี่ยนเป็นโดเมนจริงเมื่อนำขึ้นใช้งานจริง)
const APP_URL = 'http://localhost:8000';

// ดึงรหัสวิดีโอจากลิงก์ YouTube (รองรับ watch, shorts และ youtu.be) ถ้าไม่ใช่ลิงก์วิดีโอจะคืน null
function getVideoId(rawUrl) {
    let u;
    try { u = new URL(rawUrl); } catch (e) { return null; }
    const host = u.hostname.replace(/^(www|m)\./, '');
    let id = null;
    if (host === 'youtube.com') {
        if (u.pathname === '/watch') {
            id = u.searchParams.get('v');
        } else {
            const m = u.pathname.match(/^\/shorts\/([^/?#]+)/);
            if (m) id = m[1];
        }
    } else if (host === 'youtu.be') {
        id = u.pathname.slice(1).split('/')[0];
    }
    return id && /^[A-Za-z0-9_-]{6,20}$/.test(id) ? id : null;
}

const analyzeBtn = document.getElementById('analyzeBtn');
const videoBox = document.getElementById('videoBox');
const emptyMsg = document.getElementById('emptyMsg');
document.getElementById('openApp').href = APP_URL;

(async function init() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const id = tab && tab.url ? getVideoId(tab.url) : null;
    if (!id) return; // ไม่ใช่หน้าวิดีโอ: ปุ่มยังกดไม่ได้ และแสดงข้อความแนะนำเดิม

    // แสดงว่าจะสรุปวิดีโอไหน (ชื่อ + ภาพปก)
    const title = (tab.title || '').replace(/^\(\d+\)\s*/, '').replace(/\s*-\s*YouTube$/, '');
    document.getElementById('videoTitle').textContent = title || 'YouTube video';
    document.getElementById('thumb').src = 'https://i.ytimg.com/vi/' + id + '/mqdefault.jpg';
    videoBox.hidden = false;
    emptyMsg.hidden = true;
    analyzeBtn.disabled = false;

    analyzeBtn.addEventListener('click', () => {
        // ส่งเป็นลิงก์มาตรฐานที่สร้างจากรหัสวิดีโอ (ตัดพารามิเตอร์อื่น เช่น playlist หรือเวลา ออกให้)
        const cleanUrl = 'https://www.youtube.com/watch?v=' + id;
        const webAppUrl = APP_URL + '/process-extension?url=' + encodeURIComponent(cleanUrl);
        chrome.tabs.create({ url: webAppUrl, index: tab.index + 1 });
        window.close();
    });
})();
