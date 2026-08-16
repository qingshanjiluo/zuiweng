#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DZMM (www.dzmm.ai) 适配器
注册受 Cloudflare Turnstile 拦截 (需浏览器+邮箱OTP), 适配器不自动注册.
但登录与每日签到均为纯 API 且无验证码, 可全自动:
  POST /api/auth/sign-in {email,password}          -> 200, cookie (sb-rls-auth-token, 有效期1h)
  POST /api/trpc/tasks.initCheckin {"json":null}   -> {token, mirrors}
  POST /api/trpc/tasks.claim {"json":{"taskKey":"daily_checkin","checkinToken":token}}
  GET  /api/trpc/credits.getBalance                -> 积分
需 curl_cffi (chrome124 TLS 指纹) 才能通过 Turnstile 网络层.
"""
import os, random, time
from datetime import datetime, timezone, timedelta
from .base import PlatformBase, all_accounts_fields

try:
    from curl_cffi import requests as cr
except Exception:
    cr = None

BASE = "https://www.dzmm.ai"
TZ = timezone(timedelta(hours=8))
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
    s = cr.Session(impersonate="chrome124", proxies=proxies or {})
    s.headers.update(_headers())
    return s


class Platform(PlatformBase):
    name = "dzmm"
    label = "DZMM"

    def register(self, log):
        log("  DZMM 注册受 Turnstile 拦截, 需浏览器+邮箱OTP, 不支持 API 自动注册")
        return None

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