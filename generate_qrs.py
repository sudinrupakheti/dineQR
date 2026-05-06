import qrcode
import os

if not os.path.exists("media/table_qrs"):
    os.makedirs("media/table_qrs")

base_url = "http://127.0.0.1:8000/?table="  # Update this when you deploy

for table_num in range(1, 11):  # Tables 1 to 10
    url = f"{base_url}{table_num}"
    qr = qrcode.make(url)
    qr.save(f"media/table_qrs/table_{table_num}.png")
    print(f"Generated QR for Table {table_num}")