def truncate_transcript(text, max_words=10):
    """ฟังก์ชันสำหรับตัดข้อความให้เหลือแค่จำนวนคำที่กำหนด"""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])