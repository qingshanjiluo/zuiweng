#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风月酒馆 (aiaha.xyz / ai-xan.xyz 多域名) 适配器
账号为无绑定邮箱账号: 用户名来自网名库, 注册返回 jwt.
登录可用 name 当 email: POST /console/api/login {email: name, password}
"""
import os, random, string, time, requests
from datetime import datetime, timezone, timedelta
from .base import PlatformBase, all_accounts_fields

DOMAINS = ["https://ai-xan.xyz", "https://acepro.store", "https://aquantancee.xyz"]
LOGIN_DOMAINS = ["https://aiaha.xyz", "https://ai-xan.xyz", "https://acepro.store", "https://aquantancee.xyz"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))
NAMES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "网名库.txt")


def api_headers(auth=None, referer=None):
    h = {"user-agent": UA, "x-language": "zh-Hans", "x-timezone": "Asia/Shanghai",
         "accept": "application/json", "content-type": "application/json"}
    if auth:
        h["authorization"] = f"Bearer {auth}"
    if referer:
        h["referer"] = referer
    return h


def gen_password():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=8))


def load_name():
    try:
        names = [l.strip() for l in open(NAMES_FILE, encoding='utf-8')
                 if l.strip() and not l.strip().startswith('#')]
        if names:
            return random.choice(names)
    except Exception:
        pass
    return "FY" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))


class Platform(PlatformBase):
    name = "fengyue"
    label = "风月酒馆"

    # ---------- 注册 (无绑定邮箱, 滑块破解) ----------
    def register(self, log):
        s = requests.Session()
        s.headers.update(api_headers(referer="https://ai-xan.xyz/zh/register"))
        name = load_name()
        base = random.choice(DOMAINS)
        try:
            r = s.get(base + "/", timeout=30)
            r.raise_for_status()
            sd = s.get(base + "/go/api/slide/get", timeout=25).json().get("data", {})
            if not sd:
                log("  滑块无数据"); return None
            slide_id, tile_y, reg_token = sd.get("id"), sd.get("tile_y"), sd.get("reg_token")
            x_pos = list(range(0, 301, 5))
            random.shuffle(x_pos)
            ok_slide = False
            for x in x_pos:
                try:
                    j = s.post(base + "/go/api/slide/check", json={"id": slide_id, "point": f"{x},{tile_y}"}, timeout=25).json()
                    if j.get("code") == 100000:
                        ok_slide = True
                        break
                except Exception:
                    pass
                time.sleep(random.uniform(0.1, 0.2))
            if not ok_slide:
                log("  滑块破解失败"); return None
            pwd = gen_password()
            body = {"name": name, "password": pwd, "code": "", "client": "web_pc",
                    "interface_language": "zh-Hans", "reg_token": reg_token}
            j = s.post(base + "/console/api/register", json=body, timeout=30).json()
            jwt = j.get("data")
            if not (isinstance(jwt, str) and jwt.startswith("eyJ")):
                log(f"  注册失败: {str(j.get('msg') or j.get('message') or '')[:60]}")
                return None
            pts = self._points(jwt)
            return {
                "platform": self.name,
                "nickname": name, "password": pwd,
                "email": f"{name}@fengyue.local", "email_password": "",
                "user_id": jwt, "registered_at": "",
                "petals": pts, "status": "pool",
            }
        except Exception as e:
            log(f"  注册异常: {str(e)[:60]}")
            return None

    # ---------- 每日任务 (登录->积分->日历->签到->抽奖) ----------
    def daily(self, accounts, log):
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        for a in accounts:
            name, pwd = a.get("nickname"), a.get("password")
            err = None
            try:
                jwt = self._login(name, pwd)
                if not jwt:
                    err = "login失败"
                else:
                    pts = self._points(jwt)
                    signed = self._today_signed(jwt)
                    reward, sstat = None, "ALREADY" if signed else "SKIP"
                    if not signed:
                        reward, sstat = self._sign(jwt)
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
                pts, sstat, reward = None, "ERR", None
            if err:
                log(f"[{a['id']}] {name} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {name} sign={sstat} reward={reward} petals={pts}")
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": a.get("email") or "", "nickname": name,
                        "password": pwd, "petals": pts if pts is not None else a.get("petals", 0),
                        "status": a.get("status", "pool")})
            accounts_out.append(out)
            if sstat in ("SIGNED", "ALREADY"):
                signs.append({"account_id": a["id"], "date": today, "status": sstat, "reward": reward or 0})
            if pts is not None:
                points.append({"account_id": a["id"], "date": today, "petals": int(pts)})
            health.append({"account_id": a["id"], "ok": 0 if err else 1,
                           "error": err or "", "petals": pts if pts is not None else a.get("petals", 0)})
            time.sleep(2)
        return accounts_out, signs, points, health

    # ---------- 底层接口 (多域名容错) ----------
    def _login(self, name, pwd):
        for base in LOGIN_DOMAINS:
            try:
                r = requests.post(f"{base}/console/api/login", json={"email": name, "password": pwd},
                                  headers=api_headers(referer=f"{base}/zh/signin"), timeout=25)
                j = r.json()
                if j.get("result") == "success" and isinstance(j.get("data"), str):
                    return j["data"]
            except Exception:
                continue
        return None

    def _points(self, jwt):
        for base in LOGIN_DOMAINS:
            try:
                r = requests.get(f"{base}/go/api/account/point", headers=api_headers(jwt), timeout=25)
                j = r.json()
                if j.get("code") == 100000:
                    try:
                        return int(float(j["data"]["points"]))
                    except Exception:
                        return 0
            except Exception:
                continue
        return 0

    def _today_signed(self, jwt):
        for base in LOGIN_DOMAINS:
            try:
                r = requests.get(f"{base}/console/api/monthly_calendar",
                                 params={"date": datetime.now(TZ).strftime("%Y-%m")},
                                 headers=api_headers(jwt), timeout=25)
                j = r.json()
                if j.get("code") == 200:
                    today = datetime.now(TZ).strftime("%Y-%m-%d")
                    for day in j.get("data", {}).get("calendar", []):
                        if day["date"] == today:
                            return bool(day["signed"])
                    return False
            except Exception:
                continue
        return False

    def _sign(self, jwt):
        for base in LOGIN_DOMAINS:
            try:
                r = requests.get(f"{base}/console/api/sign_in", headers=api_headers(jwt), timeout=25)
                j = r.json()
                if j.get("code") == 200:
                    return j.get("data", {}).get("reward", 0), "SIGNED"
                if "今日已签到" in (j.get("msg") or ""):
                    return 0, "ALREADY"
                return None, f"ERR:{j.get('code')}"
            except Exception:
                continue
        return None, "ERR:all-domains"

    def _lottery(self, jwt, log):
        """抽奖受 '绑定白名单邮箱' 门槛限制 (guest_limit), 已按需求停用(只签到不抽奖)"""
        return