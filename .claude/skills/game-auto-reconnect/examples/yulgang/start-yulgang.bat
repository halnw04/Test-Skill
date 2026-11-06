@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM ตั้งรหัสครั้งเดียวด้วย setx (ดู README) แล้วดับเบิลคลิกไฟล์นี้เพื่อเริ่มเฝ้าทั้ง 2 ไอดี
python ..\..\scripts\reconnect_bot.py run-all -c config.yaml
pause
