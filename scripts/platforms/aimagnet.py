#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""春水酒馆 (aimagnet.vip) 适配器"""
import os, sys, time
from .base import PlatformBase, all_accounts_fields
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aimagnet_client import MailTM, Aimagnet, rand_name, rand_pwd

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")
AB = "https://aimagnet.vip"


def total_petals(bal):
    """电子魅魔总积分 = 永久花瓣(petals) + 限时积分(bonusPetals)"""
    try:
        return int(bal.get("petals") or 0) + int(bal.get("bonusPetals") or 0)
    except Exception:
        try:
            return int(bal.get("petals") or 0)
        except Exception:
            return 0


class Platform(PlatformBase):
    name = "aimagnet"
    label = "春水酒馆"

    # ---------- 注册 ----------
    def register(self, log):
        mt = MailTM()
        am = Aimagnet()
        email, epwd = mt.create()
        log(f"  邮箱 {email}")
        r = am.register_start(email)
        if r.status_code != 200:
            self.last_error = f"register/start {r.status_code}: {r.text[:120]}"
            log(f"  register/start {r.status_code}: {r.text[:120]}")
            return None
        code = mt.wait_code(email, epwd, timeout=90)
        if not code:
            self.last_error = "收码超时"
            log("  收码超时")
            return None
        log(f"  验证码 {code}")
        r = am.register_complete(email, code)
        if r.status_code != 200:
            self.last_error = f"register/complete {r.status_code}: {r.text[:120]}"
            log(f"  register/complete {r.status_code}: {r.text[:120]}")
            return None
        try:
            user, token = am.login(email, am.pwd)
        except Exception as e:
            self.last_error = f"login失败:{str(e)[:100]}"
            log(f"  login 失败: {str(e)[:100]}")
            return None
        petals = 0
        try:
            petals = total_petals(am.balance(user["id"], token))
        except Exception:
            pass
        acc = {
            "platform": self.name,
            "nickname": user.get("nickname") or rand_name(),
            "password": am.pwd, "email": email, "email_password": epwd,
            "user_id": str(user["id"]), "registered_at": str(user.get("createdAt") or ""),
            "petals": petals, "status": "pool",
        }
        return acc

    # ---------- 每日任务 ----------
    def daily(self, accounts, log):
        from aimagnet_client import rand_name  # noqa
        accounts_out, signs, points, health = [], [], [], []
        ok = 0
        today = time.strftime("%Y-%m-%d")
        for a in accounts:
            email, pwd = a.get("email"), a.get("password")
            err = None
            petals = sstat = reward = None
            try:
                petals, sstat, reward, err = self._aim_do(email, pwd, a.get("user_id"))
            except Exception as e:
                err = f"exc:{str(e)[:60]}"
            if err:
                log(f"[{a['id']}] {a.get('nickname')} FAIL {err}")
            else:
                ok += 1
                log(f"[{a['id']}] {a.get('nickname')} sign={sstat} reward={reward} petals={petals}")
            out = {k: a.get(k) or "" for k in all_accounts_fields()}
            out.update({"id": a["id"], "email": email, "nickname": a.get("nickname"),
                        "password": pwd, "petals": petals if petals is not None else a.get("petals", 0),
                        "status": a.get("status", "pool")})
            accounts_out.append(out)
            if sstat in ("SIGNED", "ALREADY"):
                signs.append({"account_id": a["id"], "date": today, "status": sstat, "reward": reward or 0})
            if petals is not None:
                points.append({"account_id": a["id"], "date": today, "petals": int(petals)})
            health.append({"account_id": a["id"], "ok": 0 if err else 1,
                           "error": err or "", "petals": petals if petals is not None else a.get("petals", 0)})
            time.sleep(3)
        return accounts_out, signs, points, health

    def _aim_login(self, email, pwd):
        import requests
        h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
        for i in range(4):
            r = requests.post(f"{AB}/v1/auth/login", json={"identifier": email, "password": pwd}, headers=h, timeout=30)
            if r.status_code == 429:
                time.sleep(15 * (i + 1))
                continue
            if r.status_code != 200:
                return None, f"login:{r.status_code}"
            return r.json(), None
        return None, "login:429(重试耗尽)"

    def _aim_do(self, email, pwd, user_id):
        """返回 (petals, sign_status, sign_reward, err)"""
        import requests
        h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
        j, err = self._aim_login(email, pwd)
        if err:
            return None, None, None, err
        tok = j["tokens"]["accessToken"]
        uid = user_id or j["user"]["id"]
        st = requests.get(f"{AB}/v1/users/signin/status", headers={**h, "authorization": f"Bearer {tok}"}, timeout=25).json()
        today_signed = bool(st.get("todaySigned"))
        reward, sstat = None, "ALREADY" if today_signed else "SKIP"
        if not today_signed:
            r = requests.post(f"{AB}/v1/users/signin", headers={**h, "authorization": f"Bearer {tok}"}, timeout=25)
            if r.status_code == 200:
                reward = r.json().get("petalsGranted")
                sstat = "SIGNED"
            else:
                sstat = f"ERR:{r.status_code}"
        petals = None
        try:
            petals = total_petals(requests.get(f"{AB}/v1/users/{uid}/balance", headers={**h, "authorization": f"Bearer {tok}"}, timeout=25).json())
        except Exception:
            pass
        return petals, sstat, reward, None