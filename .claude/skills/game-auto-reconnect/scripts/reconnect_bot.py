#!/usr/bin/env python3
"""ตัวเฝ้าเกมบนเบราว์เซอร์: ตรวจว่าหลุดจากเซิร์ฟเวอร์ แล้วล็อกอิน เลือกเซิร์ฟ
เลือกตัวละคร และเปิดบอทที่มากับตัวเกมให้ใหม่ ตามขั้นตอนในไฟล์ config

คำสั่ง:
    python reconnect_bot.py run   -c config.yaml    # เริ่มเฝ้าเกม (Ctrl+C เพื่อหยุด)
    python reconnect_bot.py run   -c config.yaml --account 2   # เฝ้าเฉพาะไอดีที่ 2
    python reconnect_bot.py run-all -c config.yaml  # เฝ้าทุกไอดีใน accounts พร้อมกัน (แยกหน้าต่าง)
    python reconnect_bot.py snap  -c config.yaml    # เปิดเกม แล้วกด Enter เพื่อเก็บภาพหน้าจอไว้ตัดเป็นรูปต้นแบบ
    python reconnect_bot.py check -c config.yaml    # ถ่ายหน้าจอตอนนี้ แล้วบอกว่าเจอรูปต้นแบบไหนบ้าง (ไว้ปรับค่า)
    python reconnect_bot.py crop  ภาพ.png x y กว้าง สูง ผลลัพธ์.png   # ตัดภาพ

ติดตั้ง:
    pip install playwright opencv-python pyyaml
"""
import argparse
import os
import re
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------- utilities

LOG_FILE = None
LOG_PREFIX = ""
ACCOUNT = {}


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {LOG_PREFIX}{msg}"
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def expand_env(value):
    """แทน {{ชื่อ}} ด้วยค่าของไอดีที่กำลังเฝ้า (จาก accounts)
    และ ${ชื่อตัวแปร} ด้วยค่าจาก environment (ใช้กับรหัสผ่าน ไม่ต้องเขียนลงไฟล์)"""
    if not isinstance(value, str):
        return value

    def acc(m):
        key = m.group(1)
        if key not in ACCOUNT:
            raise SystemExit(f"ไอดีนี้ไม่มีค่า '{key}' ใน accounts ของ config")
        return str(ACCOUNT[key])

    value = re.sub(r"\{\{(\w+)\}\}", acc, value)

    def repl(m):
        name = m.group(1)
        if name not in os.environ:
            raise SystemExit(f"ยังไม่ได้ตั้งค่าตัวแปร {name} (ดูวิธีใน README)")
        return os.environ[name]

    return re.sub(r"\$\{(\w+)\}", repl, value)


def load_config(path, account=None):
    path = Path(path).resolve()
    if not path.exists():
        raise SystemExit(f"ไม่พบไฟล์ config: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = path.parent
    cfg.setdefault("browser", {})
    cfg.setdefault("limits", {})
    cfg["_base"] = base
    cfg["templates_dir"] = (base / cfg.get("templates_dir", "templates")).resolve()
    if "game_url" not in cfg:
        raise SystemExit("config ต้องมี game_url")
    accounts = cfg.get("accounts") or []
    cfg["_account_no"] = None
    if account is not None:
        if not 1 <= account <= len(accounts):
            raise SystemExit(f"ไม่มีไอดีลำดับที่ {account} (ใน accounts มี {len(accounts)} ไอดี)")
        apply_account(cfg, account, accounts[account - 1])
    elif len(accounts) == 1:
        apply_account(cfg, 1, accounts[0])
    elif accounts:
        raise SystemExit(f"config มี {len(accounts)} ไอดี ใช้ --account <ลำดับ> หรือคำสั่ง run-all")
    return cfg


def apply_account(cfg, no, acc):
    """ให้แต่ละไอดีมีโปรไฟล์ Chrome, ไฟล์ log และตำแหน่งหน้าต่างของตัวเอง"""
    global LOG_PREFIX
    ACCOUNT.clear()
    ACCOUNT.update({k: v for k, v in acc.items() if not isinstance(v, (dict, list))})
    ACCOUNT.setdefault("name", f"ID{no}")
    cfg["_account_no"] = no
    b = cfg["browser"]
    b["profile_dir"] = acc.get("profile_dir", f"{b.get('profile_dir', 'chrome-profile')}-{no}")
    if acc.get("window"):
        b["window"] = acc["window"]
    stem = Path(cfg.get("log_file", "reconnect.log"))
    cfg["log_file"] = acc.get("log_file", f"{stem.stem}-{no}{stem.suffix}")
    LOG_PREFIX = f"[{ACCOUNT['name']}] "


# ---------------------------------------------------------------- image matching

class Vision:
    """หารูปต้นแบบบนภาพหน้าจอ: เทียบรูปร่าง (ขาวดำ) แล้วตรวจสีซ้ำ
    เพราะปุ่มที่รูปร่างเหมือนกันแต่คนละสี (เช่น AUTO ปิด=เทา / เปิด=เขียว)
    หรือปุ่มที่ถูกหน้าต่างอื่นทับจนมืด จะได้คะแนนรูปร่างเกือบ 1.00 เท่ากัน"""

    def __init__(self, templates_dir, threshold, color_tolerance=20):
        self.dir = Path(templates_dir)
        self.threshold = threshold
        self.color_tolerance = color_tolerance
        self.cache = {}

    def template(self, name):
        if name not in self.cache:
            p = self.dir / name
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                raise SystemExit(f"เปิดรูปต้นแบบไม่ได้: {p}")
            self.cache[name] = (img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        return self.cache[name]

    @staticmethod
    def screenshot(page):
        png = page.screenshot()
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        # ภาพหน้าจออาจใหญ่กว่าพิกัดหน้าเว็บ (เช่น Windows ซูม 125%) ต้องแปลงพิกัดก่อนคลิก
        css_width = page.evaluate("window.innerWidth") or img.shape[1]
        return (img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)), img.shape[1] / css_width

    def find(self, shot, name, threshold=None):
        """คืนค่า (คะแนน 0-1, จุดกึ่งกลางเป็นพิกัดภาพ) หรือ (คะแนน, None) ถ้าไม่เจอ"""
        (img, gray), _ = shot
        tpl, tpl_gray = self.template(name)
        h, w = tpl_gray.shape
        if h > gray.shape[0] or w > gray.shape[1]:
            return 0.0, None
        res = cv2.matchTemplate(gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if score < (threshold or self.threshold):
            return score, None
        if self.color_tolerance is not None:
            diff = np.abs(img[y:y + h, x:x + w].astype(np.int16) - tpl.astype(np.int16)).mean()
            if diff > self.color_tolerance:
                return min(score, 0.5), None  # รูปร่างตรงแต่สีไม่ตรง ถือว่าไม่เจอ
        return score, (x + w / 2, y + h / 2)


# ---------------------------------------------------------------- browser

class Game:
    def __init__(self, cfg, pw):
        self.cfg = cfg
        self.pw = pw
        self.browser = None
        self.context = None
        self.page = None

    def open(self):
        b = self.cfg["browser"]
        vp = b.get("viewport", {"width": 1280, "height": 800})
        if b.get("mode", "launch") == "cdp":
            # ต่อเข้ากับ Chrome ที่เปิดไว้แล้ว (เปิดด้วย --remote-debugging-port=9222)
            self.browser = self.pw.chromium.connect_over_cdp(b.get("cdp_url", "http://127.0.0.1:9222"))
            self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        else:
            profile = (self.cfg["_base"] / b.get("profile_dir", "chrome-profile")).resolve()
            args = ["--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding"]
            win = b.get("window")
            if win:  # วางหน้าต่าง เช่น ไอดี 1 ซ้าย ไอดี 2 ขวา
                args.append(f"--window-position={win.get('x', 0)},{win.get('y', 0)}")
                args.append(f"--window-size={vp['width'] + 16},{vp['height'] + 140}")
            kwargs = dict(
                user_data_dir=str(profile),
                headless=b.get("headless", False),
                viewport=vp,
                device_scale_factor=1,
                args=args,
            )
            if b.get("executable_path"):
                kwargs["executable_path"] = b["executable_path"]
            elif b.get("channel", "chrome"):
                kwargs["channel"] = b.get("channel", "chrome")
            self.context = self.pw.chromium.launch_persistent_context(**kwargs)
        self.page = self.find_game_page() or self.new_page()
        return self.page

    def find_game_page(self):
        host = re.sub(r"^https?://", "", self.cfg["game_url"]).split("/")[0]
        for p in self.context.pages:
            if not p.is_closed() and host and host in p.url:
                return p
        return None

    def new_page(self):
        pages = [p for p in self.context.pages if not p.is_closed()]
        page = pages[0] if pages else self.context.new_page()
        page.goto(self.cfg["game_url"], wait_until="domcontentloaded", timeout=60000)
        return page

    def ensure_page(self):
        """เปิดแท็บเกมใหม่ถ้าแท็บเดิมถูกปิดหรือค้าง"""
        try:
            if self.page is None or self.page.is_closed():
                raise PWError("page closed")
            self.page.evaluate("1")
        except PWError:
            log("แท็บเกมถูกปิดหรือค้าง กำลังเปิดใหม่")
            try:
                self.page = self.find_game_page() or self.new_page()
            except PWError:
                log("เบราว์เซอร์ถูกปิด กำลังเปิดใหม่")
                self.close()
                self.open()
        return self.page

    def close(self):
        for obj in (self.context, self.browser):
            try:
                if obj:
                    obj.close()
            except PWError:
                pass
        self.browser = self.context = self.page = None


# ---------------------------------------------------------------- watcher

class Watcher:
    def __init__(self, cfg, game):
        self.cfg = cfg
        self.game = game
        self.vision = make_vision(cfg)
        self.fail_dir = cfg["_base"] / "logs"
        self.unhealthy_count = 0
        self.recoveries = deque()

    # ---- checks

    def condition_hit(self, page, shot, cond):
        if "image" in cond:
            score, pos = self.vision.find(shot, cond["image"], cond.get("threshold"))
            return pos is not None, f"เจอรูป {cond['image']} ({score:.2f})"
        if "text" in cond:
            loc = page.get_by_text(cond["text"])
            return loc.count() > 0 and loc.first.is_visible(), f"เจอข้อความ '{cond['text']}'"
        if "url_contains" in cond:
            return cond["url_contains"] in page.url, f"URL มี '{cond['url_contains']}'"
        if "url_not_contains" in cond:
            return cond["url_not_contains"] not in page.url, f"URL ไม่มี '{cond['url_not_contains']}'"
        raise SystemExit(f"เงื่อนไขไม่รู้จัก: {cond}")

    def is_healthy(self, page, shot):
        """ตรวจว่าบอทในเกมยังทำงาน (ถ้าตั้งค่า healthy_when ไว้)"""
        conds = self.cfg.get("healthy_when") or []
        if isinstance(conds, dict):
            conds = [conds]
        return all(self.condition_hit(page, shot, c)[0] for c in conds)

    def check(self):
        """คืนค่า เหตุผลที่ต้องกู้คืน หรือ None ถ้าปกติ"""
        page = self.game.ensure_page()
        try:
            shot = self.vision.screenshot(page)
        except PWError as e:
            return f"ถ่ายหน้าจอไม่ได้ ({e.__class__.__name__})"
        for cond in self.cfg.get("disconnect_when") or []:
            hit, why = self.condition_hit(page, shot, cond)
            if hit:
                return f"หลุด: {why}"
        if self.cfg.get("healthy_when"):
            if self.is_healthy(page, shot):
                self.unhealthy_count = 0
            else:
                self.unhealthy_count += 1
                need = self.cfg.get("unhealthy_after", 3)
                if self.unhealthy_count >= need:
                    return f"ไม่เห็นสัญญาณบอททำงาน {self.unhealthy_count} รอบติด"
        return None

    # ---- recovery steps

    def wait_image(self, page, name, timeout, threshold=None):
        end = time.time() + timeout
        while True:
            shot = self.vision.screenshot(page)
            score, pos = self.vision.find(shot, name, threshold)
            if pos:
                return shot, pos
            if time.time() >= end:
                raise StepFailed(f"ไม่เจอรูป {name} ภายใน {timeout} วินาที (คะแนนสูงสุด {score:.2f})")
            time.sleep(1)

    def run_step(self, page, step):
        """คืนค่า False ถ้าข้ามขั้นนี้เพราะเงื่อนไข skip_if_image"""
        if "skip_if_image" in step:
            _, pos = self.vision.find(self.vision.screenshot(page), step["skip_if_image"])
            if pos:
                return False
        timeout = step.get("timeout", self.cfg.get("step_timeout", 30))
        threshold = step.get("threshold")
        if "click_image" in step:
            step = {**step, "click_image": expand_env(step["click_image"])}
        if "goto" in step:
            url = self.cfg["game_url"] if step["goto"] in ("game_url", True) else expand_env(step["goto"])
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        elif "reload" in step:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        elif "wait" in step:
            time.sleep(float(step["wait"]))
        elif "wait_image" in step:
            self.wait_image(page, step["wait_image"], timeout, threshold)
        elif "click_image" in step:
            (_, scale), (x, y) = self.wait_image(page, step["click_image"], timeout, threshold)
            ox, oy = step.get("offset", [0, 0])
            page.mouse.click(x / scale + ox, y / scale + oy)
        elif "click_xy" in step:
            x, y = step["click_xy"]
            page.mouse.click(x, y)
        elif "click_text" in step:
            page.get_by_text(expand_env(step["click_text"])).first.click(timeout=timeout * 1000)
        elif "click_selector" in step:
            page.locator(step["click_selector"]).first.click(timeout=timeout * 1000)
        elif "fill" in step:
            f = step["fill"]
            page.locator(f["selector"]).first.fill(expand_env(f["text"]), timeout=timeout * 1000)
        elif "type" in step:
            page.keyboard.type(expand_env(step["type"]), delay=50)
        elif "press" in step:
            page.keyboard.press(step["press"])
        else:
            raise SystemExit(f"ขั้นตอนไม่รู้จัก: {step}")
        return True

    def recover(self):
        page = self.game.ensure_page()
        for i, step in enumerate(self.cfg.get("recovery_steps") or [], 1):
            label = step.get("name") or ", ".join(f"{k}={v}" for k, v in step.items()
                                                 if k not in ("optional", "timeout", "name", "skip_if_image"))
            try:
                if not self.run_step(page, step):
                    log(f"  ขั้นที่ {i}: {label} - ข้าม (เห็น {step['skip_if_image']} อยู่แล้ว)")
                    continue
                log(f"  ขั้นที่ {i}: {label} ✓")
                time.sleep(float(step.get("after", self.cfg.get("step_delay", 1))))
            except (StepFailed, PWError) as e:
                if step.get("optional"):
                    log(f"  ขั้นที่ {i}: {label} - ข้าม (ไม่จำเป็น)")
                    continue
                raise StepFailed(f"ขั้นที่ {i} ({label}) ล้มเหลว: {str(e).splitlines()[0]}") from None
        # ยืนยันผลหลังกู้คืน
        time.sleep(self.cfg.get("verify_delay", 3))
        reason = self.check()
        if reason:
            raise StepFailed(f"ทำครบทุกขั้นแล้ว แต่ยังผิดปกติ: {reason}")

    def save_fail_shot(self, tag):
        try:
            self.fail_dir.mkdir(exist_ok=True)
            p = self.fail_dir / f"fail_{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
            self.game.page.screenshot(path=str(p))
            log(f"  เก็บภาพหน้าจอไว้ที่ {p}")
        except Exception:  # noqa: BLE001
            pass

    def loop(self):
        lim = self.cfg["limits"]
        interval = self.cfg.get("check_interval", 10)
        max_tries = lim.get("max_attempts_in_a_row", 5)
        retry_wait = lim.get("retry_wait", 30)
        per_hour = lim.get("max_recoveries_per_hour", 10)
        max_runtime = self.cfg.get("max_runtime_minutes")
        started = time.time()
        log(f"เริ่มเฝ้าเกม {self.cfg['game_url']} (ตรวจทุก {interval} วินาที) กด Ctrl+C เพื่อหยุด")
        while True:
            if max_runtime and time.time() - started > max_runtime * 60:
                log("ครบเวลาที่ตั้งไว้ หยุดทำงาน")
                return
            reason = self.check()
            if reason:
                now = time.time()
                while self.recoveries and now - self.recoveries[0] > 3600:
                    self.recoveries.popleft()
                if len(self.recoveries) >= per_hour:
                    log(f"กู้คืนครบ {per_hour} ครั้งในชั่วโมงนี้แล้ว พักจนกว่าจะครบชั่วโมง (กันการล็อกอินถี่เกินไป)")
                    time.sleep(max(60, 3600 - (now - self.recoveries[0])))
                    continue
                log(f"⚠️ {reason} → เริ่มกู้คืน")
                self.recoveries.append(now)
                wait = retry_wait
                for attempt in range(1, max_tries + 1):
                    try:
                        self.recover()
                        log(f"✅ กลับเข้าเกมและเปิดบอทแล้ว (ครั้งที่ {attempt})")
                        self.unhealthy_count = 0
                        break
                    except StepFailed as e:
                        log(f"❌ ครั้งที่ {attempt}/{max_tries}: {e}")
                        self.save_fail_shot(f"try{attempt}")
                        if attempt == max_tries:
                            log(f"กู้คืนไม่สำเร็จ {max_tries} ครั้งติด หยุดทำงาน กรุณาตรวจเกมด้วยตัวเอง")
                            return 2
                        log(f"  รอ {wait} วินาทีแล้วลองใหม่")
                        time.sleep(wait)
                        wait = min(wait * 2, 600)
            time.sleep(interval)


class StepFailed(Exception):
    pass


def make_vision(cfg):
    return Vision(cfg["templates_dir"], cfg.get("match_threshold", 0.85), cfg.get("color_tolerance", 20))


# ---------------------------------------------------------------- commands

def cmd_run(cfg):
    global LOG_FILE
    LOG_FILE = cfg["_base"] / cfg.get("log_file", "reconnect.log")
    with sync_playwright() as pw:
        game = Game(cfg, pw)
        game.open()
        try:
            return Watcher(cfg, game).loop() or 0
        except KeyboardInterrupt:
            log("หยุดโดยผู้ใช้")
            return 0
        finally:
            if cfg["browser"].get("mode", "launch") != "cdp":
                game.close()


def cmd_snap(cfg):
    out_dir = cfg["_base"] / "shots"
    out_dir.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        game = Game(cfg, pw)
        page = game.open()
        print("เล่นเกมไปที่หน้าที่ต้องการ แล้วกด Enter ในหน้าต่างนี้เพื่อเก็บภาพ (พิมพ์ q แล้ว Enter เพื่อจบ)")
        n = len(list(out_dir.glob("shot_*.png")))
        while input().strip().lower() != "q":
            n += 1
            p = out_dir / f"shot_{n}.png"
            game.ensure_page().screenshot(path=str(p))
            print(f"บันทึก {p}  (เปิดด้วย Paint แล้วตัดเฉพาะปุ่ม/ข้อความ บันทึกลงโฟลเดอร์ templates)")
        if cfg["browser"].get("mode", "launch") != "cdp":
            game.close()
        _ = page


def cmd_check(cfg):
    vision = make_vision(cfg)
    with sync_playwright() as pw:
        game = Game(cfg, pw)
        page = game.open()
        if cfg["browser"].get("mode", "launch") != "cdp":
            input("ไปที่หน้าจอที่ต้องการตรวจ แล้วกด Enter...")
        shot = vision.screenshot(page)
        print(f"URL: {page.url}   สเกลภาพ: {shot[1]:.2f}")
        for p in sorted(cfg["templates_dir"].glob("*.png")):
            score, pos = vision.find(shot, p.name)
            mark = "✅ เจอ" if pos else "  ไม่เจอ"
            print(f"{mark}  {p.name:30s} คะแนน {score:.2f}" + (f" ที่ ({pos[0]:.0f},{pos[1]:.0f})" if pos else ""))
        if cfg["browser"].get("mode", "launch") != "cdp":
            game.close()


def cmd_run_all(config_path):
    cfg = load_config(config_path, account=1) if (yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}).get("accounts") else None
    if cfg is None:
        raise SystemExit("run-all ต้องมี accounts ใน config")
    n = len(cfg["accounts"])
    procs = []
    for i in range(1, n + 1):
        cmd = [sys.executable, str(Path(__file__).resolve()), "run", "-c", str(config_path), "--account", str(i)]
        procs.append(subprocess.Popen(cmd))
        print(f"เริ่มเฝ้าไอดีที่ {i} (process {procs[-1].pid})", flush=True)
        time.sleep(cfg.get("stagger_seconds", 5))  # เว้นระยะ ไม่ให้ล็อกอินพร้อมกัน
    try:
        codes = [p.wait() for p in procs]
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        codes = [p.wait() for p in procs]
    return max(codes)


def cmd_crop(src, x, y, w, h, out):
    img = cv2.imread(src)
    if img is None:
        raise SystemExit(f"เปิดภาพไม่ได้: {src}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(out, img[y:y + h, x:x + w])
    print(f"บันทึก {out} ({w}x{h})")


def main():
    ap = argparse.ArgumentParser(description="ตัวเฝ้าเกม: หลุดแล้วต่อใหม่อัตโนมัติ")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "snap", "check", "run-all"):
        sp = sub.add_parser(name)
        sp.add_argument("-c", "--config", default="config.yaml")
        if name != "run-all":
            sp.add_argument("-a", "--account", type=int, help="ลำดับไอดีใน accounts (1, 2, ...)")
    cp = sub.add_parser("crop")
    cp.add_argument("src")
    for k in ("x", "y", "w", "h"):
        cp.add_argument(k, type=int)
    cp.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "crop":
        return cmd_crop(a.src, a.x, a.y, a.w, a.h, a.out)
    if a.cmd == "run-all":
        return cmd_run_all(a.config)
    cfg = load_config(a.config, a.account)
    return {"run": cmd_run, "snap": cmd_snap, "check": cmd_check}[a.cmd](cfg)


if __name__ == "__main__":
    sys.exit(main() or 0)
