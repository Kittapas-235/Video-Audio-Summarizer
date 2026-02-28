import pytest
from summarizer import truncate_transcript

# กรณีที่ 1: ข้อความสั้นกว่าค่าสูงสุด (ต้องคืนค่าเดิมกลับมา)
def test_truncate_under_limit():
    text = "Hello world"
    result = truncate_transcript(text, max_words=5)
    assert result == "Hello world"

# กรณีที่ 2: ข้อความยาวเกินกำหนด (ต้องตัดทิ้งให้เหลือตามจำนวนที่ระบุ)
def test_truncate_over_limit():
    text = "This is a very long sentence for testing"
    result = truncate_transcript(text, max_words=3)
    assert result == "This is a"
    assert len(result.split()) == 3

# กรณีที่ 3: ส่งค่าว่างเข้าไป (ต้องได้ค่าว่างกลับมา)
def test_truncate_empty_string():
    assert truncate_transcript("", max_words=10) == ""