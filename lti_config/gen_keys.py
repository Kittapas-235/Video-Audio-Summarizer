# gen_keys.py
from Crypto.PublicKey import RSA

# สร้างกุญแจ RSA 2048-bit
key = RSA.generate(2048)
private_key = key.export_key()
public_key = key.publickey().export_key()

# บันทึกลงไฟล์
with open("private.key", "wb") as f:
    f.write(private_key)

with open("public.key", "wb") as f:
    f.write(public_key)

print("✅ สร้างกุญแจ private.key และ public.key เรียบร้อยแล้ว!")