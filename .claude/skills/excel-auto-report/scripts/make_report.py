#!/usr/bin/env python3
"""สร้างรายงาน Excel อัตโนมัติจากไฟล์ .xlsx / .xls / .csv

วิธีใช้:
    python make_report.py ข้อมูล.xlsx
    python make_report.py ข้อมูล.csv --group สาขา --value ยอดขาย --date วันที่ -o รายงาน.xlsx

ถ้าไม่ระบุ --group / --value / --date สคริปต์จะเดาคอลัมน์ให้เอง
ผลลัพธ์: ไฟล์ Excel ที่มีชีต ภาพรวม, คุณภาพข้อมูล, สรุปตามกลุ่ม (+กราฟ),
รายเดือน (+กราฟ ถ้ามีคอลัมน์วันที่) และข้อมูลดิบ
และพิมพ์สรุปเป็น JSON ออกทางหน้าจอ ให้ Claude นำไปเขียนบทวิเคราะห์ต่อ

ต้องมี: pip install pandas openpyxl
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
MAX_GROUPS_IN_CHART = 15
warnings.filterwarnings("ignore", category=UserWarning)


def read_any(path: Path, sheet):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        for enc in ("utf-8-sig", "cp874", "tis-620"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError:
                continue
        raise SystemExit(f"อ่านไฟล์ CSV ไม่ได้ (ลองบันทึกเป็น UTF-8): {path}")
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
    raise SystemExit(f"ไม่รองรับไฟล์ชนิด {suffix} (รองรับ .csv .xlsx .xls)")


def is_text(series):
    return not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series)


def to_number(series):
    """แปลงข้อความอย่าง "1,200 บาท" หรือ "฿500" เป็นตัวเลข"""
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = series.astype(str).str.replace(r"[,\s฿]|บาท", "", regex=True)
    return pd.to_numeric(cleaned.where(series.notna()), errors="coerce")


def guess_date_col(df):
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    for c in [c for c in df.columns if is_text(df[c])]:
        sample = df[c].dropna().astype(str).head(50)
        if len(sample) == 0:
            continue
        parsed = pd.to_datetime(sample, errors="coerce", dayfirst=True)
        if parsed.notna().mean() >= 0.6:
            return c
    return None


def guess_value_col(df, exclude):
    nums = []
    for c in df.columns:
        if c in exclude or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        s = df[c].dropna()
        if len(s) and to_number(s).notna().mean() >= 0.8:
            nums.append(c)
    if not nums:
        return None
    # เลือกคอลัมน์ตัวเลขที่ผลรวมมากที่สุด (มักเป็นยอดเงิน/ยอดขาย) แต่ไม่ใช่รหัส/ลำดับ
    def score(c):
        s = to_number(df[c])
        looks_like_id = s.is_monotonic_increasing and s.nunique() == len(s)
        return (0 if looks_like_id else 1, float(s.abs().sum()))
    return max(nums, key=score)


def guess_group_col(df, exclude):
    best, best_n = None, None
    for c in df.columns:
        if c in exclude:
            continue
        if not is_text(df[c]):
            continue
        n = df[c].nunique()
        if 2 <= n <= 50 and (best_n is None or n < best_n):
            best, best_n = c, n
    return best


def style_sheet(ws):
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for col in ws.columns:
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 4, 10), 50)
        for c in col[1:]:
            if isinstance(c.value, float):
                c.number_format = "#,##0.00"
            elif isinstance(c.value, int):
                c.number_format = "#,##0"
    ws.freeze_panes = "A2"


def main():
    ap = argparse.ArgumentParser(description="สร้างรายงาน Excel อัตโนมัติ")
    ap.add_argument("input", help="ไฟล์ข้อมูล .xlsx / .xls / .csv")
    ap.add_argument("-o", "--output", help="ไฟล์รายงานที่จะสร้าง (ค่าเริ่มต้น: <ชื่อไฟล์>_รายงาน.xlsx)")
    ap.add_argument("--sheet", help="ชื่อชีตที่จะอ่าน (ค่าเริ่มต้น: ชีตแรก)")
    ap.add_argument("--group", help="คอลัมน์ที่ใช้จัดกลุ่ม เช่น สาขา, สินค้า")
    ap.add_argument("--value", help="คอลัมน์ตัวเลขที่จะสรุป เช่น ยอดขาย")
    ap.add_argument("--date", help="คอลัมน์วันที่ (ใช้ทำสรุปรายเดือน)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"ไม่พบไฟล์: {src}")
    out = Path(args.output) if args.output else src.with_name(f"{src.stem}_รายงาน.xlsx")

    df = read_any(src, args.sheet)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    if df.empty:
        raise SystemExit("ไฟล์ไม่มีข้อมูล")

    for name, col in (("--group", args.group), ("--value", args.value), ("--date", args.date)):
        if col and col not in df.columns:
            raise SystemExit(f"ไม่พบคอลัมน์ {col!r} ({name}). คอลัมน์ที่มี: {list(df.columns)}")

    date_col = args.date or guess_date_col(df)
    buddhist_year = False
    if date_col:
        raw_dates = df[date_col]
        df[date_col] = pd.to_datetime(raw_dates, errors="coerce", dayfirst=True)
        years = df[date_col].dropna().dt.year
        if len(years) and years.median() > 2400:  # ปี พ.ศ. -> แปลงเป็น ค.ศ.
            buddhist_year = True
            df[date_col] = df[date_col] - pd.DateOffset(years=543)
    value_col = args.value or guess_value_col(df, exclude={date_col})
    group_col = args.group or guess_group_col(df, exclude={date_col, value_col})
    if value_col:
        before = df[value_col].notna().sum()
        df[value_col] = to_number(df[value_col])
        bad_numbers = int(before - df[value_col].notna().sum())

    summary = {
        "ไฟล์": src.name,
        "จำนวนแถว": int(len(df)),
        "จำนวนคอลัมน์": int(df.shape[1]),
        "แถวซ้ำ": int(df.duplicated().sum()),
        "คอลัมน์วันที่": date_col,
        "คอลัมน์ตัวเลขหลัก": value_col,
        "คอลัมน์จัดกลุ่ม": group_col,
    }
    if value_col and bad_numbers:
        summary["ตัวเลขอ่านไม่ได้"] = bad_numbers
    if date_col:
        summary["วันที่อ่านไม่ได้"] = int(df[date_col].isna().sum() - raw_dates.isna().sum())
        if buddhist_year:
            summary["หมายเหตุวันที่"] = "พบปี พ.ศ. แปลงเป็น ค.ศ. แล้ว (ลบ 543)"

    quality = pd.DataFrame({
        "คอลัมน์": df.columns,
        "ชนิดข้อมูล": [str(t) for t in df.dtypes],
        "ค่าว่าง": [int(df[c].isna().sum()) for c in df.columns],
        "ค่าว่าง (%)": [round(df[c].isna().mean() * 100, 1) for c in df.columns],
        "ค่าไม่ซ้ำ": [int(df[c].nunique()) for c in df.columns],
    })
    summary["คอลัมน์ที่มีค่าว่าง"] = {
        r["คอลัมน์"]: r["ค่าว่าง"] for _, r in quality.iterrows() if r["ค่าว่าง"] > 0
    }

    by_group = None
    if group_col and value_col:
        by_group = (
            df.groupby(group_col, dropna=False)[value_col]
            .agg(["sum", "count", "mean"])
            .rename(columns={"sum": "ยอดรวม", "count": "จำนวนรายการ", "mean": "ค่าเฉลี่ย"})
            .sort_values("ยอดรวม", ascending=False)
            .reset_index()
        )
        total = by_group["ยอดรวม"].sum()
        by_group["สัดส่วน (%)"] = (by_group["ยอดรวม"] / total * 100).round(1) if total else 0
        by_group[group_col] = by_group[group_col].fillna("(ว่าง)").astype(str)
        summary["ยอดรวมทั้งหมด"] = round(float(total), 2)
        summary["อันดับสูงสุด 5"] = by_group.head(5)[[group_col, "ยอดรวม", "สัดส่วน (%)"]].to_dict("records")
    elif value_col:
        summary["ยอดรวมทั้งหมด"] = round(float(df[value_col].sum()), 2)

    monthly = None
    if date_col and value_col and df[date_col].notna().any():
        monthly = (
            df.dropna(subset=[date_col])
            .groupby(df[date_col].dt.to_period("M"))[value_col]
            .agg(["sum", "count"])
            .rename(columns={"sum": "ยอดรวม", "count": "จำนวนรายการ"})
            .reset_index()
        )
        monthly["เดือน"] = monthly[date_col].astype(str)
        monthly = monthly[["เดือน", "ยอดรวม", "จำนวนรายการ"]]
        monthly["เปลี่ยนแปลงจากเดือนก่อน (%)"] = (monthly["ยอดรวม"].pct_change() * 100).round(1)
        summary["รายเดือน"] = monthly.fillna("").to_dict("records")

    if value_col:
        s = df[value_col].dropna()
        if len(s):
            summary["สถิติ " + value_col] = {
                "ต่ำสุด": round(float(s.min()), 2),
                "สูงสุด": round(float(s.max()), 2),
                "เฉลี่ย": round(float(s.mean()), 2),
                "มัธยฐาน": round(float(s.median()), 2),
            }

    overview = pd.DataFrame(
        [(k, v) for k, v in summary.items() if not isinstance(v, (dict, list))],
        columns=["หัวข้อ", "ค่า"],
    )

    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        overview.to_excel(xw, sheet_name="ภาพรวม", index=False)
        quality.to_excel(xw, sheet_name="คุณภาพข้อมูล", index=False)
        if by_group is not None:
            by_group.to_excel(xw, sheet_name="สรุปตามกลุ่ม", index=False)
        if monthly is not None:
            monthly.to_excel(xw, sheet_name="รายเดือน", index=False)
        raw = df.copy()
        if date_col:
            raw[date_col] = raw[date_col].dt.date
        raw.to_excel(xw, sheet_name="ข้อมูลดิบ", index=False)

    wb = load_workbook(out)
    for ws in wb.worksheets:
        style_sheet(ws)

    if by_group is not None:
        ws = wb["สรุปตามกลุ่ม"]
        n = min(len(by_group), MAX_GROUPS_IN_CHART)
        ch = BarChart()
        ch.title = f"{value_col} ตาม {group_col}" + (f" (สูงสุด {n} อันดับ)" if len(by_group) > n else "")
        ch.y_axis.title = value_col
        ch.add_data(Reference(ws, min_col=2, min_row=1, max_row=n + 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
        ch.height, ch.width, ch.legend = 9, 18, None
        ws.add_chart(ch, "H2")

    if monthly is not None and len(monthly) >= 2:
        ws = wb["รายเดือน"]
        ch = LineChart()
        ch.title = f"{value_col} รายเดือน"
        ch.add_data(Reference(ws, min_col=2, min_row=1, max_row=len(monthly) + 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=len(monthly) + 1))
        ch.height, ch.width, ch.legend = 9, 18, None
        ws.add_chart(ch, "G2")

    wb.save(out)
    summary["ไฟล์รายงาน"] = str(out)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
