#!/usr/bin/env python3
"""บอกเวลาประเทศไทย และสภาพอากาศปัจจุบัน + พยากรณ์ 3 วัน (ข้อมูลจาก Open-Meteo ฟรี ไม่ต้องใช้ API key)

วิธีใช้:
    python thai_weather.py                 # เวลา + อากาศกรุงเทพฯ
    python thai_weather.py เชียงใหม่         # ระบุจังหวัด
    python thai_weather.py --time          # บอกเวลาอย่างเดียว (ไม่ใช้อินเทอร์เน็ต)
    python thai_weather.py --lat 13.1 --lon 100.9 --name "บ้าน"

ใช้แค่ไลบรารีมาตรฐานของ Python ไม่ต้องติดตั้งอะไรเพิ่ม
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TH_TZ = timezone(timedelta(hours=7))
TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
TH_MONTHS_SHORT = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

# พิกัดศาลากลาง/ตัวเมืองโดยประมาณของจังหวัดที่ใช้บ่อย (จังหวัดอื่นจะค้นจาก Open-Meteo)
PROVINCES = {
    "กรุงเทพ": (13.7563, 100.5018), "กรุงเทพมหานคร": (13.7563, 100.5018), "bangkok": (13.7563, 100.5018),
    "นนทบุรี": (13.8621, 100.5144), "ปทุมธานี": (14.0208, 100.5250), "สมุทรปราการ": (13.5991, 100.5968),
    "เชียงใหม่": (18.7883, 98.9853), "เชียงราย": (19.9105, 99.8406), "ลำปาง": (18.2888, 99.4909),
    "พิษณุโลก": (16.8211, 100.2659), "นครสวรรค์": (15.7047, 100.1372),
    "ขอนแก่น": (16.4322, 102.8236), "อุดรธานี": (17.4138, 102.7872), "นครราชสีมา": (14.9799, 102.0978),
    "โคราช": (14.9799, 102.0978), "อุบลราชธานี": (15.2287, 104.8564),
    "ชลบุรี": (13.3611, 100.9847), "พัทยา": (12.9236, 100.8825), "ระยอง": (12.6814, 101.2816),
    "จันทบุรี": (12.6114, 102.1039), "อยุธยา": (14.3532, 100.5689), "พระนครศรีอยุธยา": (14.3532, 100.5689),
    "กาญจนบุรี": (14.0228, 99.5328), "หัวหิน": (12.5684, 99.9577), "ประจวบคีรีขันธ์": (11.8124, 99.7973),
    "ภูเก็ต": (7.8804, 98.3923), "กระบี่": (8.0863, 98.9063), "สุราษฎร์ธานี": (9.1382, 99.3215),
    "เกาะสมุย": (9.5120, 100.0136), "หาดใหญ่": (7.0086, 100.4747), "สงขลา": (7.1898, 100.5954),
    "นครศรีธรรมราช": (8.4304, 99.9631),
}

# รหัสสภาพอากาศ WMO -> ภาษาไทย
WEATHER_TH = {
    0: "ท้องฟ้าแจ่มใส ☀️", 1: "ค่อนข้างแจ่มใส 🌤️", 2: "มีเมฆบางส่วน ⛅", 3: "เมฆมาก ☁️",
    45: "มีหมอก 🌫️", 48: "หมอกน้ำค้างแข็ง 🌫️",
    51: "ฝนปรอยเบา 🌦️", 53: "ฝนปรอย 🌦️", 55: "ฝนปรอยหนาแน่น 🌧️",
    61: "ฝนเล็กน้อย 🌦️", 63: "ฝนปานกลาง 🌧️", 65: "ฝนหนัก 🌧️",
    66: "ฝนเยือกแข็งเบา 🌧️", 67: "ฝนเยือกแข็ง 🌧️",
    71: "หิมะเล็กน้อย 🌨️", 73: "หิมะ 🌨️", 75: "หิมะหนัก 🌨️", 77: "เกล็ดหิมะ 🌨️",
    80: "ฝนตกเป็นช่วง ๆ 🌦️", 81: "ฝนตกเป็นช่วง ๆ ปานกลาง 🌧️", 82: "ฝนตกหนักเป็นช่วง ๆ ⛈️",
    85: "หิมะตกเป็นช่วง ๆ 🌨️", 86: "หิมะตกหนักเป็นช่วง ๆ 🌨️",
    95: "พายุฝนฟ้าคะนอง ⛈️", 96: "พายุฝนฟ้าคะนอง มีลูกเห็บ ⛈️", 99: "พายุฝนฟ้าคะนอง ลูกเห็บหนัก ⛈️",
}


def thai_date(dt, with_time=True):
    s = f"วัน{TH_DAYS[dt.weekday()]}ที่ {dt.day} {TH_MONTHS[dt.month - 1]} พ.ศ. {dt.year + 543}"
    return s + (f" เวลา {dt:%H:%M} น." if with_time else "")


def describe(code):
    return WEATHER_TH.get(code, f"ไม่ทราบ (รหัส {code})")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "thai-time-weather-skill"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def find_place(name):
    key = name.strip().lower().replace("จังหวัด", "").replace("จ.", "").strip()
    if key in PROVINCES:
        return name, *PROVINCES[key]
    q = urllib.parse.urlencode({"name": key, "count": 5, "language": "th", "format": "json"})
    data = get_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}")
    results = data.get("results") or []
    th = [r for r in results if r.get("country_code") == "TH"] or results
    if not th:
        raise SystemExit(f"หาสถานที่ '{name}' ไม่พบ ลองพิมพ์ชื่อจังหวัดเต็ม หรือใช้ --lat/--lon")
    r = th[0]
    return r.get("name", name), r["latitude"], r["longitude"]


def fetch_weather(lat, lon):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Bangkok", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
    })
    return get_json(f"https://api.open-meteo.com/v1/forecast?{q}")


def format_report(place, data):
    c = data["current"]
    d = data["daily"]
    lines = [
        f"🌡️ อากาศที่ {place} (ข้อมูล ณ {c['time'][-5:]} น.)",
        f"- สภาพ: {describe(c['weather_code'])}",
        f"- อุณหภูมิ: {c['temperature_2m']:.1f}°C (รู้สึกเหมือน {c['apparent_temperature']:.1f}°C)",
        f"- ความชื้น: {c['relative_humidity_2m']}%   ลม: {c['wind_speed_10m']:.0f} กม./ชม.   ฝนตอนนี้: {c['precipitation']} มม.",
        "",
        "📅 พยากรณ์ 3 วัน",
    ]
    for i, day in enumerate(d["time"]):
        dt = datetime.fromisoformat(day)
        label = ["วันนี้", "พรุ่งนี้", "มะรืนนี้"][i] if i < 3 else day
        rain = d["precipitation_probability_max"][i]
        lines.append(
            f"- {label} ({dt.day} {TH_MONTHS_SHORT[dt.month - 1]}): {describe(d['weather_code'][i])} "
            f"{d['temperature_2m_min'][i]:.0f}-{d['temperature_2m_max'][i]:.0f}°C "
            f"โอกาสฝน {f'{rain}%' if rain is not None else '-'} UV {d['uv_index_max'][i]}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="เวลาและสภาพอากาศประเทศไทย")
    ap.add_argument("place", nargs="?", default="กรุงเทพ", help="ชื่อจังหวัด/เมือง (ค่าเริ่มต้น: กรุงเทพ)")
    ap.add_argument("--time", action="store_true", help="แสดงเฉพาะเวลา")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--name", help="ชื่อที่จะแสดง เมื่อใช้ --lat/--lon")
    ap.add_argument("--json", action="store_true", help="แสดงข้อมูลดิบจาก API")
    args = ap.parse_args()

    print("🕐 " + thai_date(datetime.now(TH_TZ)) + " (เวลาประเทศไทย UTC+7)")
    if args.time:
        return
    if args.lat is not None and args.lon is not None:
        place, lat, lon = args.name or f"{args.lat},{args.lon}", args.lat, args.lon
    else:
        place, lat, lon = find_place(args.place)
    try:
        data = fetch_weather(lat, lon)
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️ ดึงข้อมูลอากาศไม่สำเร็จ: {e}\n(ตรวจอินเทอร์เน็ต หรือเครือข่ายอาจบล็อก api.open-meteo.com)")
        sys.exit(2)
    print()
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_report(place, data))


if __name__ == "__main__":
    main()
