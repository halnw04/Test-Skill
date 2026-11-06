# Test-Skill

ชุดสกิลภาษาไทยสำหรับ Claude

| สกิล | ทำอะไร | ตัวอย่างคำสั่ง |
|---|---|---|
| `thai-doc-summary` | สรุปเอกสารเป็นภาษาไทยตามรูปแบบมาตรฐาน | "สรุปไฟล์นี้ให้หน่อย" หรือ `/thai-doc-summary report.pdf สั้น` |
| `excel-auto-report` | ทำรายงาน Excel อัตโนมัติ มีกราฟและบทวิเคราะห์ | "ทำรายงานยอดขายจาก sales.xlsx" |
| `thai-time-weather` | บอกเวลาไทย (พ.ศ.) และอากาศพร้อมพยากรณ์ 3 วัน | "อากาศเชียงใหม่วันนี้เป็นไง" |
| `claude-best-practice-th` | คู่มือใช้ Claude Code ภาษาไทย และเช็กลิสต์สร้างสกิล | "สร้างสกิลยังไงให้ดี" |
| `game-auto-reconnect` | เฝ้าเกมบน Chrome ถ้าหลุดจะล็อกอิน เลือกเซิร์ฟ เลือกตัวละคร และเปิดบอทของเกมให้ใหม่ รองรับหลายไอดี | "เกมหลุดบ่อย ช่วยตั้งค่าตัวเฝ้าเกมให้หน่อย" (คู่มือ: `.claude/skills/game-auto-reconnect/examples/yulgang/README.md`) |

## วิธีติดตั้ง

### Claude Code บนคลาวด์ (claude.ai/code หรือแอป)
เปิดเซสชันใหม่โดยเลือก repo นี้ สกิลในโฟลเดอร์ `.claude/skills/` จะโหลดให้อัตโนมัติ

### Claude Code บนคอมพิวเตอร์
```bash
git clone https://github.com/halnw04/Test-Skill.git
```
```bash
cp -r Test-Skill/.claude/skills/* ~/.claude/skills/
```
คำสั่งที่ 2 ทำให้ทุกโปรเจกต์ใช้สกิลเหล่านี้ได้ ถ้าต้องการใช้แค่โปรเจกต์เดียว ให้ copy ไปไว้ที่ `<โปรเจกต์>/.claude/skills/` แทน

### claude.ai (เว็บ/แอป)
1. ดาวน์โหลดไฟล์ zip จากโฟลเดอร์ `dist/` (1 ไฟล์ต่อ 1 สกิล)
2. ไปที่ **Settings → Capabilities → Skills** แล้วอัปโหลด

## สิ่งที่ต้องมี
- **`game-auto-reconnect`**: ต้องมี Windows หรือ Mac, Google Chrome, Python 3 และติดตั้งไลบรารีด้วยคำสั่ง `pip install -r .claude/skills/game-auto-reconnect/requirements.txt` สกิลนี้ทำงานบนเครื่องของคุณ ไม่ใช่บนคลาวด์
- **`excel-auto-report`**: ต้องมี Python 3 และติดตั้งไลบรารีด้วยคำสั่ง `pip install pandas openpyxl`
- **`thai-time-weather`**: ต้องมี Python 3 และต่ออินเทอร์เน็ตได้ (ดึงข้อมูลจาก api.open-meteo.com)

## วิธีเช็กว่าสกิลใช้ได้
เปิดเซสชันใหม่ แล้วพิมพ์ `/` ควรเห็นชื่อสกิลทั้ง 4 ในรายการ

## เครดิต
เนื้อหาใน `claude-best-practice-th` เรียบเรียงจาก [shanraisshan/claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice) (MIT License)
