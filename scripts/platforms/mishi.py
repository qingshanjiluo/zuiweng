#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密丝AI (missai.me / www.miss001.org) 适配器
注册与每日签到均为纯 API, 可全自动:
  注册 (requests 直连即可, 无需 curl_cffi/代理):
    POST /api/gva/base/captcha                      -> {captchaId, picPath(6位数字图)}
    ddddocr 识别数字验证码 (页面提供"改用数字验证码"切换, 即此接口)
    POST /api/gva/user/register_and_login {userName, passWord, inviteCode(可空),
           deviceFingerprint, captcha, captchaId}  + header X-Device-Fingerprint
           -> {user{ID,uuid}, token}
  每日签到:
    POST /api/gva/base/login {username, password}   -> {token}
    GET  /api/gva/checkin/status                    -> {hasCheckedIn, todayReward}
    POST /api/gva/checkin/sign                      -> 签到, 得体验点
    GET  /api/gva/pointsAcc/getUserPointsAccount    -> 总积分 = combinedBalance
  鉴权头: x-token  (非 Authorization)
  邀请码: env MISSAI_INVITE, 为空则不带 (AB67E50C 曾可用, 现已失效)
  邮箱认证: /api/gva/email/sendVerificationCode + /api/gva/email/verifyAndBind
            (mail.tm 可收码, 奖励发放机制待确认)
"""
import os, re, time, base64, random, string
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base import PlatformBase, all_accounts_fields, is_dup_error

try:
    import requests
except Exception:
    requests = None

BASE = "https://missai.me"
ORIG = "https://www.miss001.org"
INVITE = os.environ.get("MISSAI_INVITE", "")
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
        "referer": ORIG + "/register?inviteCode=" + (INVITE or "none"),
    }


def _session():
    if requests is None:
        return None
    s = requests.Session()
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
        s = _session()
        if not s:
            self.last_error = "no-requests"
            log("  no-requests")
            return None
        try:
            s.get(ORIG + "/", timeout=30)
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 1.5))
        capid, code = self._captcha(s)
        if not capid:
            self.last_error = "验证码OCR多次失败"
            log("  验证码 OCR 多次失败")
            return None
        # 重名重试: 循环生成新名直到成功或遇非重名错误
        last_msg = ""
        for _ in range(5):
            uname = getattr(self.gen, "next")("missai") if self.gen else _rand_user()
            pwd = _rand_pwd()
            fp = _rand_fp()
            body = {"userName": uname, "passWord": pwd, "nickName": uname, "email": "",
                    "phone": "", "headerImg": "", "enable": 1,
                    "inviteCode": INVITE, "deviceFingerprint": fp,
                    "captcha": code, "captchaId": capid}
            time.sleep(random.uniform(1, 2))
            try:
                r = s.post(ORIG + "/api/gva/user/register_and_login", json=body,
                           headers={**_headers(), "x-device-fingerprint": fp}, timeout=30)
                j = r.json()
            except Exception as e:
                last_msg = f"网络异常:{str(e)[:60]}"
                break
            # code=None/missing 表示空响应(被限流), code!=0 为业务错误
            code = j.get("code")
            if code is None:
                # 空响应=被限流, 等待后重试当前用户名
                log(f"  空响应, 等15s后重试")
                time.sleep(15)
                try:
                    r = s.post(ORIG + "/api/gva/user/register_and_login", json=body,
                               headers={**_headers(), "x-device-fingerprint": fp}, timeout=30)
                    j = r.json()
                    code = j.get("code")
                except Exception as e:
                    last_msg = f"重试网络异常:{str(e)[:60]}"
                    break
                if code is None:
                    last_msg = "空响应(被限流)"
                    break
            if code != 0:
                last_msg = f"{j.get('msg')}"
                if is_dup_error(last_msg):
                    log(f"  重名({last_msg[:30]}), 换名重试")
                    continue
                break
            d = j.get("data") or {}
            user = d.get("user") or {}
            uid = user.get("ID") or user.get("id")
            if not uid or not d.get("token"):
                last_msg = "注册返回缺少uid/token"
                log(f"  DEBUG resp: code={code} data_keys={list(d.keys())} user_keys={list(user.keys())}")
                break
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
        self.last_error = last_msg
        log(f"  注册失败: {last_msg[:100]}")
        return None

    # ---------- 每日任务 (登录->签到->积分) ----------
    def daily(self, accounts, log):
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = time.strftime("%Y-%m-%d")
        workers = int(os.environ.get("MISSAI_WORKERS", "20"))

        def process(a):
            uname, pwd = a.get("email"), a.get("password")
            err = None
            pts = sstat = reward = None
            try:
                s = _session()
                if not s:
                    err = "no-requests"
                else:
                    try:
                        s.get(ORIG + "/", timeout=30)
                    except Exception:
                        pass
                    time.sleep(random.uniform(0.3, 1.0))
                    j = s.post(ORIG + "/api/gva/base/login",
                               json={"username": uname, "password": pwd}, timeout=30).json()
                    code = j.get("code")
                    if code is None or code != 0:
                        err = f"login失败:{j.get('msg') or '空响应'}"
                    else:
                        tok = j["data"]["token"]
                        pts, sstat, reward = self._do_sign(s, tok)
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
                sstat = "ERR"
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": uname, "nickname": a.get("nickname") or uname,
                        "password": pwd, "petals": pts if pts is not None else a.get("petals", 0),
                        "status": a.get("status", "pool")})
            sign_rec = None
            if sstat in ("SIGNED", "ALREADY"):
                sign_rec = {"account_id": a["id"], "date": today, "status": sstat, "reward": reward or 0}
            point_rec = None
            if pts is not None:
                point_rec = {"account_id": a["id"], "date": today, "petals": int(pts)}
            health_rec = {"account_id": a["id"], "ok": 0 if err else 1,
                          "error": err or "", "petals": pts if pts is not None else a.get("petals", 0)}
            return a, uname, err, sstat, reward, pts, out, sign_rec, point_rec, health_rec

        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(process, a) for a in accounts]
            for f in as_completed(futures):
                results.append(f.result())
        results.sort(key=lambda r: r[0]["id"])
        for (a, uname, err, sstat, reward, pts, out, sign_rec, point_rec, health_rec) in results:
            if err:
                log(f"[{a['id']}] {uname} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {uname} sign={sstat} reward={reward} pts={pts}")
            accounts_out.append(out)
            if sign_rec:
                signs.append(sign_rec)
            if point_rec:
                points.append(point_rec)
            health.append(health_rec)
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
        code = j.get("code")
        if code is None or code != 0:
            if "今日已签到" in str(j.get("msg")):
                return self._points(s, tok), "ALREADY", 0
            return self._points(s, tok), f"ERR:{j.get('msg') or '空响应'}", None
        return self._points(s, tok), "SIGNED", int(d.get("todayReward") or 0)