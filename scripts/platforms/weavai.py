#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI织梦 (weavai.app) 适配器
注册与每日签到均为纯 API, 可全自动:
  注册 (每 IP 只能注册 1 个账号, 需轮换 IP):
    GET https://api.mail.tm/domains                -> 临时邮箱域名
    POST https://api.mail.tm/accounts              -> 建临时邮箱 (可选)
    POST {supabase}/auth/v1/signup                 -> 注册, 直接返回 access_token (邮箱自动确认)
    POST {supabase}/functions/v1/weavai-billing    -> checkin_status / checkin (每日签到 +1200)
                                                    -> onboarding_status / onboarding_claim (day_index=1, +5000)
  每日签到 (用已存 token 或重新登录, 无 IP 限制):
    POST {supabase}/auth/v1/token?grant_type=password  -> 登录
    POST .../weavai-billing {action:checkin}       -> 签到
  限流: 同一出口 IP 只能成功注册 1 个账号 (signup 永远 200, 但 billing 接口
        对超限 IP 返回 409 ip_limit_reached). 批量注册需轮换出口 IP:
        - GitHub Actions: 每个 job 是全新 runner IP
        - 本地: 通过 WEAVAI_PROXY 指定 socks5 代理 (轮换节点)
  头: X-WeavAI-Client: app (billing 必须), apikey + authorization 均为公开 publishable key
"""
import os, time, json, random, string
from .base import PlatformBase, all_accounts_fields

try:
    import requests
except Exception:
    requests = None

BASE = "https://uigewencailuxfdpyzzv.supabase.co"
BILL = BASE + "/functions/v1/weavai-billing"
KEY = "sb_publishable_6SH7OxyahzCtbq1YzZXDPg_Tazic9Th"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")
PROXY = os.environ.get("WEAVAI_PROXY", "")   # 例: socks5://127.0.0.1:10809
# 每 IP 可注册的账号数上限 (weavai 服务端限制)
IP_REG_LIMIT = int(os.environ.get("WEAVAI_IP_LIMIT", "1"))


def _proxy_dict():
    if not PROXY:
        return None
    return {"http": PROXY, "https": PROXY}


def _rand_pwd():
    return "Wv" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "1"


def _rand_name():
    return "wv" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _headers(tok=None):
    h = {
        "user-agent": UA,
        "accept": "application/json",
        "content-type": "application/json",
        "apikey": KEY,
        "authorization": "Bearer " + (tok or KEY),
        "origin": "https://weavai.app",
        "referer": "https://weavai.app/",
        "X-WeavAI-Client": "app",
    }
    return h


class Platform(PlatformBase):
    name = "weavai"
    label = "AI织梦"

    # ---------- 注册 ----------
    def register(self, log):
        if requests is None:
            self.last_error = "no-requests"
            log("  no-requests")
            return None
        px = _proxy_dict()
        try:
            return self._register(px, log)
        except Exception as e:
            self.last_error = f"异常:{str(e)[:100]}"
            log(f"  register 异常: {str(e)[:100]}")
            return None

    def _register(self, px, log):
        # 1. 临时邮箱 (mail.tm)
        try:
            r = requests.get("https://api.mail.tm/domains", proxies=px, timeout=20)
            dom = r.json()["hydra:member"][0]["domain"]
        except Exception:
            dom = ""  # 无邮箱也注册 (email 仅作展示)
        em = ""
        if dom:
            em = _rand_name() + str(int(time.time() * 1000))[-6:] + "@" + dom
            try:
                requests.post("https://api.mail.tm/accounts",
                              json={"address": em, "password": "TmpMail!1"},
                              proxies=px, timeout=20)
            except Exception:
                pass
        pw = _rand_pwd()
        disp = _rand_name()
        # 2. Supabase 注册
        body = {"email": em, "password": pw,
                "data": {"display_name": disp, "full_name": disp, "name": disp}}
        time.sleep(random.uniform(0.8, 2.0))
        r = requests.post(BASE + "/auth/v1/signup", headers=_headers(),
                          json=body, timeout=30, proxies=px)
        try:
            j = r.json()
        except Exception:
            j = {}
        tok = j.get("access_token")
        if not tok:
            msg = j.get("msg") or j.get("message") or j.get("error_description") or r.text[:100]
            self.last_error = f"signup失败:{r.status_code}:{str(msg)[:100]}"
            log(f"  signup 失败: {r.status_code} {str(msg)[:100]}")
            return None
        # 3. 领取奖励
        petals = 0
        try:
            petals = self._claim(px, tok, log)
        except Exception as e:
            log(f"  领奖异常: {str(e)[:80]}")
        # IP 限流时放弃该账号 (浪费 IP 且产生死号)
        if self.last_error == "ip_limit_reached":
            log(f"  该出口 IP 已达注册上限, 放弃账号")
            return None
        acc = {
            "platform": self.name,
            "nickname": disp,
            "password": pw,
            "email": em or disp + "@local",
            "email_password": "",
            "user_id": str(j.get("user", {}).get("id") or ""),
            "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "petals": petals, "status": "pool",
        }
        return acc

    def _claim(self, px, tok, log):
        AH = _headers(tok)
        pts = 0
        # onboarding day1 = 5000
        for day, rp in ((1, 5000),):
            r = requests.post(BILL, headers=AH,
                              json={"action": "onboarding_claim", "claim_all_eligible": True,
                                    "day_index": day, "lang": ""},
                              timeout=25, proxies=px)
            try:
                j = r.json()
                if j.get("success"):
                    pts += int(j.get("reward_points") or rp)
                    log(f"  onboarding day{day}: +{j.get('reward_points')}分")
                else:
                    log(f"  onboarding day{day}: {j.get('message','')[:60]}")
            except Exception:
                pass
            time.sleep(random.uniform(0.5, 1.5))
        # checkin = 1200
        r = requests.post(BILL, headers=AH, json={"action": "checkin", "lang": ""},
                          timeout=25, proxies=px)
        try:
            j = r.json()
            if j.get("success") or j.get("claimed") or j.get("already_claimed"):
                b = int(j.get("bonus_points") or 0)
                pts += b
                log(f"  签到: +{b}分")
            else:
                code = j.get("code")
                if code == "ip_limit_reached":
                    self.last_error = "ip_limit_reached"
                log(f"  签到: {j.get('message','')[:60]}")
        except Exception:
            pass
        return pts

    # ---------- 每日任务 (登录->签到->积分) ----------
    def daily(self, accounts, log):
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = time.strftime("%Y-%m-%d")
        for a in accounts:
            em, pw = a.get("email"), a.get("password")
            err = None
            pts = sstat = reward = None
            try:
                j = requests.post(BASE + "/auth/v1/token?grant_type=password",
                                  headers=_headers(),
                                  json={"email": em, "password": pw},
                                  timeout=30).json()
                tok = j.get("access_token")
                if not tok:
                    err = f"登录失败:{str(j.get('error_description') or j.get('error') or '空响应')[:60]}"
                else:
                    pts, sstat, reward = self._do_sign(tok)
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
                sstat = "ERR"
            if err:
                log(f"[{a['id']}] {em} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {em} sign={sstat} reward={reward} pts={pts}")
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": em, "nickname": a.get("nickname") or em,
                        "password": pw, "petals": pts if pts is not None else a.get("petals", 0),
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

    def _do_sign(self, tok):
        AH = _headers(tok)
        st = requests.post(BILL, headers=AH, json={"action": "checkin_status", "lang": ""},
                           timeout=25).json()
        if st.get("claimed_today") or st.get("already_claimed"):
            b = int(st.get("bonus_points") or 0)
            return self._points(tok), "ALREADY", b
        r = requests.post(BILL, headers=AH, json={"action": "checkin", "lang": ""}, timeout=25)
        try:
            j = r.json()
        except Exception:
            j = {}
        if j.get("success") or j.get("claimed") or j.get("already_claimed"):
            b = int(j.get("bonus_points") or 0)
            return self._points(tok), "SIGNED", b
        code = j.get("code")
        if code == "ip_limit_reached":
            return 0, "IP_LIMIT", None
        return self._points(tok), f"ERR:{str(j.get('message') or '')[:40]}", None

    def _points(self, tok):
        try:
            r = requests.post(BILL, headers=_headers(tok),
                              json={"action": "overview", "lang": ""}, timeout=25)
            j = r.json()
            w = j.get("wallet") or {}
            return int(w.get("balance_points") or 0)
        except Exception:
            return 0