#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DZMM (www.dzmm.ai) 适配器
注册受 Cloudflare Turnstile 拦截, 需真实浏览器(headless Chromium)+邮箱OTP:
  Playwright 填注册表 -> Turnstile 自动通过 -> mail.tm 收验证码 -> 完成注册
登录与每日签到为纯 API 且无验证码, 可全自动:
  POST /api/auth/sign-in {email,password}          -> 200, cookie (sb-rls-auth-token, 有效期1h)
  POST /api/trpc/tasks.initCheckin {"json":null}   -> {token, mirrors}
  POST /api/trpc/tasks.claim {"json":{"taskKey":"daily_checkin","checkinToken":token}}
  GET  /api/trpc/credits.getBalance                -> 积分
需 curl_cffi (chrome124 TLS 指纹) 才能通过 Turnstile 网络层.
"""
import os, random, string, time, re
from datetime import datetime, timezone, timedelta
from .base import PlatformBase, all_accounts_fields

try:
    from curl_cffi import requests as cr
except Exception:
    cr = None

try:
    import requests
except Exception:
    requests = None

try:
    from playwright.sync_api import sync_playwright
    _HAS_PW = True
except Exception:
    _HAS_PW = False

MT = "https://api.mail.tm"
BASE = "https://www.dzmm.ai"
TZ = timezone(timedelta(hours=8))
PROXY = os.environ.get("PROXY_URL", "")
TRPC_IN = "%7B%22json%22%3Anull%2C%22meta%22%3A%7B%22values%22%3A%5B%22undefined%22%5D%2C%22v%22%3A1%7D%7D"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")


def _headers():
    return {
        "user-agent": UA,
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "origin": BASE,
        "referer": BASE + "/tasks",
    }


def _session(proxies=None):
    if cr is None:
        return None
    px = proxies or PROXY or {}
    if isinstance(px, str):
        px = {"http": px, "https": px}
    s = cr.Session(impersonate="chrome124", proxies=px)
    s.headers.update(_headers())
    return s


class Platform(PlatformBase):
    name = "dzmm"
    label = "DZMM"

    def register(self, log):
        if not _HAS_PW:
            self.last_error = "no-playwright"
            log("  no-playwright")
            return None
        # 1. 创建临时邮箱 (mail.tm)
        addr, mpwd = self._make_mailbox()
        if not addr:
            self.last_error = "mail.tm 创建失败"
            log(f"  {self.last_error}")
            return None
        log(f"  邮箱 {addr}")
        app_pwd = "Dz" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "1"
        # 2. Playwright 浏览器注册
        uid, petals = self._browser_register(addr, app_pwd, mpwd, log)
        if not uid:
            return None
        return {
            "platform": self.name,
            "nickname": addr.split("@")[0],
            "password": app_pwd, "email": addr, "email_password": mpwd,
            "user_id": str(uid), "registered_at": "",
            "petals": petals, "status": "pool",
        }

    # ---------- 注册: mail.tm 邮箱 ----------
    def _make_mailbox(self):
        if requests is None:
            return None, None
        h = {"user-agent": UA, "content-type": "application/json"}
        addr = "dz" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@emalupe.com"
        pwd = "MailTmp" + "".join(random.choices(string.ascii_letters + string.digits, k=6)) + "1"
        for _ in range(6):
            try:
                r = requests.post(MT + "/accounts", json={"address": addr, "password": pwd}, headers=h, timeout=25)
                if r.status_code in (201, 422):
                    return addr, pwd
            except Exception:
                pass
            time.sleep(random.uniform(2, 4))
        return None, None

    def _wait_code(self, addr, mpwd, timeout=120):
        if requests is None:
            return None
        h = {"user-agent": UA, "content-type": "application/json"}
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                r = requests.post(MT + "/token", json={"address": addr, "password": mpwd}, headers=h, timeout=25)
                if r.status_code == 200:
                    mh = {"authorization": "Bearer " + r.json()["token"], "user-agent": UA}
                    r2 = requests.get(MT + "/messages", headers=mh, timeout=25)
                    msgs = r2.json().get("hydra:member", [])
                    if msgs:
                        mid = msgs[0]["id"]
                        full = requests.get(f"{MT}/messages/{mid}", headers=mh, timeout=25).json()
                        raw = (full.get("intro") or "") + " " + (full.get("text") or "")
                        clean = re.sub(r"[\s\u200b\u200c\u200d\ufeff]", "", raw)
                        codes = re.findall(r"\d{4,8}", clean)
                        if codes:
                            return codes[0]
            except Exception:
                pass
            time.sleep(5)
        return None

    # ---------- 注册: Playwright 浏览器流程 ----------
    def _browser_register(self, addr, app_pwd, mpwd, log):
        try:
            launch_kwargs = {"headless": os.environ.get("DZMM_HEADFUL", "0") != "1",
                             "args": ["--disable-blink-features=AutomationControlled"]}
            if PROXY:
                launch_kwargs["proxy"] = {"server": PROXY}
            with sync_playwright() as p:
                browser = p.chromium.launch(**launch_kwargs)
                ctx = browser.new_context(
                    user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 800})
                ctx.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = ctx.new_page()
                page.goto(BASE + "/sign-in?s=signup", timeout=60000)
                page.wait_for_timeout(2500)
                page.fill("input[type=email]", addr)
                page.fill("input[type=password]", app_pwd)
                # 勾选协议
                try:
                    page.check("input[type=checkbox]", timeout=5000)
                except Exception:
                    page.evaluate("() => { const el = document.querySelector('input[type=checkbox]'); if (el && !el.checked) el.click(); }")
                page.wait_for_timeout(1200)
                page.click("button:has-text('注册')", timeout=10000)
                # 轮询等待进入验证页 (Turnstile 验证耗时不定)
                body = ""
                for _ in range(15):
                    page.wait_for_timeout(1500)
                    try:
                        body = page.inner_text("body")
                    except Exception:
                        body = ""
                    if "同意并" in body:
                        try:
                            page.click("button:has-text('同意并')", timeout=5000)
                        except Exception:
                            pass
                        continue
                    if "验证你的邮箱" in body:
                        break
                if "验证你的邮箱" not in body:
                    self.last_error = f"未进入验证页: {body[:100]}"
                    log(f"  未进入验证页: {body[:80]}")
                    browser.close()
                    return None, 0
                # 收验证码
                code = self._wait_code(addr, mpwd, timeout=120)
                if not code:
                    self.last_error = "验证码收码超时"
                    log(f"  验证码收码超时")
                    browser.close()
                    return None, 0
                log(f"  验证码 {code}")
                page.locator('input[maxlength="8"]').fill(code)
                page.wait_for_timeout(800)
                page.click("button:has-text('验证')", timeout=8000)
                page.wait_for_timeout(5000)
                url = page.url
                browser.close()
                if not url.startswith(BASE + "/"):
                    self.last_error = "注册后未登录"
                    log(f"  注册后未登录 url={url}")
                    return None, 0
                # 3. API 登录拿 user_id + 积分
                uid, petals = self._api_login_petals(addr, app_pwd)
                if not uid:
                    self.last_error = "注册成功但API登录失败"
                    log(f"  注册成功但API登录失败")
                    return None, 0
                log(f"  注册OK user_id={uid} petals={petals}")
                return uid, petals
        except Exception as e:
            self.last_error = f"浏览器异常:{str(e)[:100]}"
            log(f"  浏览器异常: {str(e)[:80]}")
            return None, 0

    def _api_login_petals(self, addr, app_pwd):
        if cr is None:
            return None, 0
        try:
            s = _session()
            if not s:
                return None, 0
            s.get(BASE + "/", timeout=30)
            j = s.post(BASE + "/api/auth/sign-in",
                       json={"email": addr, "password": app_pwd}, timeout=30).json()
            u = j.get("user") or {}
            if not u.get("id"):
                return None, 0
            return u["id"], self._points(s)
        except Exception:
            return None, 0

    # ---------- 每日任务 (登录->积分->签到) ----------
    def daily(self, accounts, log):
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} \
            if os.environ.get("LOCAL_PROXY") else {}
        for a in accounts:
            email, pwd = a.get("email"), a.get("password")
            err = None
            pts = None
            sstat, reward = "SKIP", None
            try:
                s = _session(proxies)
                if not s:
                    err = "no-curl_cffi"
                else:
                    s.get(BASE + "/", timeout=30)
                    time.sleep(random.uniform(0.5, 1.5))
                    j = s.post(BASE + "/api/auth/sign-in",
                               json={"email": email, "password": pwd}, timeout=30).json()
                    if not j.get("user") or not j.get("user", {}).get("id"):
                        err = "login失败"
                    else:
                        uid = j["user"]["id"]
                        pts = self._points(s)
                        claimed = self._today_signed(s)
                        if claimed:
                            sstat, reward = "ALREADY", 0
                        else:
                            reward, sstat = self._sign(s)
                        pts = self._points(s)
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
                sstat = "ERR"
            if err:
                log(f"[{a['id']}] {email} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {email} sign={sstat} reward={reward} pts={pts}")
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": email, "nickname": a.get("nickname") or email,
                        "password": pwd, "petals": pts if pts is not None else a.get("petals", 0),
                        "status": a.get("status", "pool")})
            accounts_out.append(out)
            if sstat in ("SIGNED", "ALREADY"):
                signs.append({"account_id": a["id"], "date": today, "status": sstat, "reward": reward or 0})
            if pts is not None:
                points.append({"account_id": a["id"], "date": today, "petals": int(pts)})
            health.append({"account_id": a["id"], "ok": 0 if err else 1,
                           "error": err or "", "petals": pts if pts is not None else a.get("petals", 0)})
            time.sleep(random.uniform(1, 2.5))
        return accounts_out, signs, points, health

    # ---------- 底层接口 ----------
    def _points(self, s):
        try:
            r = s.get(BASE + "/api/trpc/credits.getBalance?input=" + TRPC_IN, timeout=25)
            j = r.json()
            d = j.get("result", {}).get("data", {}).get("json", {})
            return int(d.get("total", 0) or 0)
        except Exception:
            return 0

    def _today_signed(self, s):
        try:
            r = s.get(BASE + "/api/trpc/tasks.list?input=" + TRPC_IN, timeout=25)
            j = r.json()
            tasks = j.get("result", {}).get("data", {}).get("json", {}).get("tasks", [])
            for t in tasks:
                if t.get("key") == "daily_checkin":
                    return bool(t.get("claimed"))
            return False
        except Exception:
            return False

    def _sign(self, s):
        try:
            r = s.post(BASE + "/api/trpc/tasks.initCheckin", json={"json": None}, timeout=25)
            token = r.json()["result"]["data"]["json"]["token"]
            time.sleep(random.uniform(0.5, 1.5))
            r = s.post(BASE + "/api/trpc/tasks.claim",
                       json={"json": {"taskKey": "daily_checkin", "checkinToken": token}}, timeout=25)
            j = r.json()
            if j.get("result", {}).get("data", {}).get("json", {}).get("success"):
                return 5, "SIGNED"
            return None, "ERR"
        except Exception:
            return None, "ERR"