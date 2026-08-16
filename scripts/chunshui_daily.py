#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · GitHub Actions 每日任务: 拉取号池 -> 逐个登录签到/探活 -> 同步回 Worker
env: ZUIWENG_API (Worker 地址) / ADMIN_TOKEN (Worker 管理令牌)
"""
import os, sys, io, time, datetime, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = os.environ.get("ZUIWENG_API", "https://zuiweng-api.sifangzhiji.workers.dev")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36")
TODAY = datetime.datetime.utcnow().strftime("%Y-%m-%d")

def http(method, url, json=None, token=None):
    h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
    if token:
        h["authorization"] = f"Bearer {token}"
    r = requests.request(method, url, json=json, headers=h, timeout=30)
    return r

def aim_login(email, pwd):
    import time as _t
    for i in range(4):
        r = http("POST", "https://aimagnet.vip/v1/auth/login", {"identifier": email, "password": pwd})
        if r.status_code == 429:
            _t.sleep(15 * (i + 1))
            continue
        if r.status_code != 200:
            return None, f"login:{r.status_code}"
        j = r.json()
        return j, None
    return None, "login:429(重试耗尽)"

def aim_do(email, pwd, user_id):
    """返回 (petals, sign_status, sign_reward, err)"""
    j, err = aim_login(email, pwd)
    if err:
        return None, None, None, err
    tok = j["tokens"]["accessToken"]
    uid = user_id or j["user"]["id"]
    # 签到状态
    st = http("GET", f"https://aimagnet.vip/v1/users/signin/status", token=tok).json()
    today_signed = bool(st.get("todaySigned"))
    reward = None
    sstat = "ALREADY" if today_signed else "SKIP"
    if not today_signed:
        r = http("POST", "https://aimagnet.vip/v1/users/signin", token=tok)
        if r.status_code == 200:
            rr = r.json()
            reward = rr.get("petalsGranted")
            sstat = "SIGNED"
        else:
            sstat = f"ERR:{r.status_code}"
    # 花瓣
    petals = None
    try:
        petals = http("GET", f"https://aimagnet.vip/v1/users/{uid}/balance", token=tok).json().get("petals")
    except Exception:
        pass
    return petals, sstat, reward, None

def main():
    if not ADMIN:
        print("缺少 ADMIN_TOKEN")
        sys.exit(1)
    r = http("GET", f"{API}/api/admin/chunshui/accounts", token=ADMIN)
    if r.status_code != 200:
        print("拉号池失败", r.status_code, r.text[:200]); sys.exit(1)
    accs = r.json()["data"]["accounts"]
    print(f"号池 {len(accs)} 个账号, 日期 {TODAY}")

    accounts_out, signs, points, health = [], [], [], []
    ok = 0
    for a in accs:
        email, pwd = a["email"], a["password"]
        try:
            petals, sstat, reward, err = aim_do(email, pwd, a.get("user_id"))
        except Exception as e:
            err = f"exc:{str(e)[:60]}"
            petals, sstat, reward = None, "ERR", None
        ok_flag = 1 if not err else 0
        if err:
            print(f"[{a['id']}] {a['nickname']} FAIL {err}")
        else:
            ok += 1
            print(f"[{a['id']}] {a['nickname']} sign={sstat} reward={reward} petals={petals}")
        accounts_out.append({"id": a["id"], "email": a["email"], "nickname": a["nickname"], "password": a["password"],
                             "email_password": a.get("email_password") or "", "user_id": a.get("user_id") or "",
                             "registered_at": a.get("registered_at") or "", "petals": petals if petals is not None else a["petals"],
                             "status": a["status"]})
        if sstat in ("SIGNED", "ALREADY"):
            signs.append({"account_id": a["id"], "date": TODAY, "status": sstat, "reward": reward or 0})
        if petals is not None:
            points.append({"account_id": a["id"], "date": TODAY, "petals": int(petals)})
        health.append({"account_id": a["id"], "ok": ok_flag, "error": err or "", "petals": petals if petals is not None else a["petals"]})
        time.sleep(3)

    body = {"accounts": accounts_out, "sign_records": signs, "points": points, "health": health}
    r = http("POST", f"{API}/api/chunshui/sync", body, token=ADMIN)
    print("同步:", r.status_code, r.text[:200])
    print(f"完成: 正常 {ok}/{len(accs)}, 签到 {len(signs)}")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()