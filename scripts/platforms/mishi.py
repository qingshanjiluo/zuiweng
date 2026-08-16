#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密丝AI (missai.me / www.miss001.org) 适配器
注册与每日签到均为纯 API, 可全自动:
  注册:
    POST /api/gva/base/captcha                      -> {captchaId, picPath(6位数字图)}
    ddddocr 识别数字验证码 (页面提供"改用数字验证码"切换, 即此接口)
    POST /api/gva/user/register_and_login {userName, passWord, inviteCode:"AB67E50C",
           deviceFingerprint, captcha, captchaId}  + header X-Device-Fingerprint
           -> {user{ID,uuid}, token} (邀请码奖励 1000 永久积分)
  每日签到:
    POST /api/gva/base/login {username, password}   -> {token}
    GET  /api/gva/checkin/status                    -> {hasCheckedIn, todayReward}
    POST /api/gva/checkin/sign                      -> 签到, 得体验点
    GET  /api/gva/pointsAcc/getUserPointsAccount    -> 总积分 = combinedBalance
  鉴权头: x-token  (非 Authorization)
  邮箱认证: /api/gva/email/sendVerificationCode + /api/gva/email/verifyAndBind
            (mail.tm 可收码, 认证奖励发放机制待确认)
"""
import os, re, time, base64, random, string
from .base import PlatformBase, all_accounts_fields

try:
    from curl_cffi import requests as cr
except Exception:
    cr = None

BASE = "https://missai.me"
ORIG = "https://www.miss001.org"
INVITE = "AB67E50C"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")
_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        import ddddocr
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr


def _headers():
    return {
        "user-agent": UA,
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": ORIG,
        "referer": ORIG + "/register?inviteCode=" + INVITE,
    }


def _session(proxies=None):
    if cr is None:
        return None
    s = cr.Session(impersonate="chrome124", proxies=proxies or {})
    s.headers.update(_headers())
    return s


def _rand_user():
    return "ms" + "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def _rand_pwd():
    return "Ms" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "1"


def _rand_fp():
    return "".join(random.choices("0123456789abcdef", k=32))


class Platform(PlatformBase):
    name = "missai"
    label = "密丝AI"

    # ---------- 注册 ----------
    def register(self, log):
        proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} \
            if os.environ.get("LOCAL_PROXY") else {}
        s = _session(proxies)
        if not s:
            log("  无 curl_cffi")
            return None
        s.get(ORIG + "/", timeout=30)
        time.sleep(random.uniform(0.5, 1.5))
        capid, code = self._captcha(s)
        if not capid:
            log("  验证码 OCR 多次失败")
            return None
        uname, pwd = _rand_user(), _rand_pwd()
        fp = _rand_fp()
        body = {"userName": uname, "passWord": pwd, "nickName": uname, "email": "",
                "phone": "", "headerImg": "", "enable": 1, "inviteCode": INVITE,
                "deviceFingerprint": fp, "captcha": code, "captchaId": capid}
        r = s.post(ORIG + "/api/gva/user/register_and_login", json=body,
                   headers={**_headers(), "x-device-fingerprint": fp}, timeout=30)
        try:
            j = r.json()
        except Exception:
            log(f"  注册响应非 JSON: {r.status_code}")
            return None
        if (j.get("code") or 0) != 0:
            log(f"  注册失败: {j.get('msg')}")
            return None
        d = j.get("data") or {}
        user = d.get("user") or {}
        uid = user.get("ID") or user.get("id")
        if not uid or not d.get("token"):
            log("  注册返回缺少 uid/token")
            return None
        petals = 0
        try:
            petals = self._points(s, d["token"])
        except Exception:
            pass
        acc = {
            "platform": self.name,
            "nickname": uname,
            "password": pwd, "email": uname, "email_password": "",
            "user_id": str(uid), "registered_at": str(user.get("CreatedAt") or ""),
            "petals": petals, "status": "pool",
        }
        return acc

    # ---------- 每日任务 (登录->签到->积分) ----------
    def daily(self, accounts, log):
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = time.strftime("%Y-%m-%d")
        proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} \
            if os.environ.get("LOCAL_PROXY") else {}
        for a in accounts:
            uname, pwd = a.get("email"), a.get("password")
            err = None
            pts = sstat = reward = None
            try:
                s = _session(proxies)
                if not s:
                    err = "no-curl_cffi"
                else:
                    s.get(ORIG + "/", timeout=30)
                    time.sleep(random.uniform(0.5, 1.5))
                    j = s.post(ORIG + "/api/gva/base/login",
                               json={"username": uname, "password": pwd}, timeout=30).json()
                    if (j.get("code") or 0) != 0:
                        err = f"login失败:{j.get('msg')}"
                    else:
                        tok = j["data"]["token"]
                        pts, sstat, reward = self._do_sign(s, tok)
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
                sstat = "ERR"
            if err:
                log(f"[{a['id']}] {uname} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {uname} sign={sstat} reward={reward} pts={pts}")
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": uname, "nickname": a.get("nickname") or uname,
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
    def _captcha(self, s):
        ocr = _get_ocr()
        for _ in range(10):
            try:
                r = s.post(ORIG + "/api/gva/base/captcha", timeout=30)
                d = (r.json().get("data") or {})
                capid = d.get("captchaId") or ""
                pic = d.get("picPath") or ""
                if not capid or not pic:
                    continue
                img = base64.b64decode(pic.split(",", 1)[1])
                code = re.sub(r"[^0-9]", "", ocr.classification(img))
                if len(code) == 6:
                    return capid, code
            except Exception:
                continue
        return None, None

    def _points(self, s, tok):
        j = s.get(ORIG + "/api/gva/pointsAcc/getUserPointsAccount",
                  headers={**s.headers, "x-token": tok}, timeout=25).json()
        d = j.get("data") or {}
        return int(d.get("combinedBalance") or 0)

    def _do_sign(self, s, tok):
        AH = {**s.headers, "x-token": tok}
        st = s.get(ORIG + "/api/gva/checkin/status", headers=AH, timeout=25).json()
        d = st.get("data") or {}
        if d.get("hasCheckedIn"):
            return self._points(s, tok), "ALREADY", 0
        r = s.post(ORIG + "/api/gva/checkin/sign", headers=AH, json={}, timeout=25)
        j = r.json()
        if (j.get("code") or 0) != 0:
            if "今日已签到" in str(j.get("msg")):
                return self._points(s, tok), "ALREADY", 0
            return self._points(s, tok), f"ERR:{j.get('msg')}", None
        return self._points(s, tok), "SIGNED", int(d.get("todayReward") or 0)
