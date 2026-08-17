#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · 多平台每日任务: 拉号池 -> 按平台分发 签到/探活 -> 同步回 Worker
env: ZUIWENG_API / ADMIN_TOKEN
配置: scripts/platforms.json (daily=true 的平台会被执行)
"""
import os, sys, io, time, datetime, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from platforms import load_config, build_platforms

API = os.environ.get("ZUIWENG_API", "https://zuiweng-api.sifangzhiji.workers.dev")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
PLATFORM = os.environ.get("PLATFORM", "")       # 指定平台, 空=全部
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36")
TODAY = datetime.datetime.utcnow().strftime("%Y-%m-%d")

def http(method, url, json=None, token=None):
    h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
    if token:
        h["authorization"] = f"Bearer {token}"
    return requests.request(method, url, json=json, headers=h, timeout=30)

def main():
    if not ADMIN:
        print("缺少 ADMIN_TOKEN"); sys.exit(1)
    plats = build_platforms(load_config())
    dailies = {n: p for n, p in plats.items() if getattr(p, "daily_enabled", False)}
    if PLATFORM:
        dailies = {n: p for n, p in dailies.items() if n == PLATFORM}
    if not dailies:
        print("无启用的每日平台 (platforms.json)"); sys.exit(1)

    r = http("GET", f"{API}/api/admin/chunshui/accounts?limit=5000", token=ADMIN)
    if r.status_code != 200:
        print("拉号池失败", r.status_code, r.text[:200]); sys.exit(1)
    accs = r.json()["data"]["accounts"]
    if len(accs) >= 4990:   # 号池超 5000 时按分页补拉
        seen = {a["id"] for a in accs}
        off = 5000
        while True:
            r2 = http("GET", f"{API}/api/admin/chunshui/accounts?limit=5000&offset={off}", token=ADMIN)
            page = r2.json()["data"]["accounts"]
            if not page:
                break
            for a in page:
                if a["id"] not in seen:
                    accs.append(a); seen.add(a["id"])
            if len(page) < 5000:
                break
            off += 5000
    print(f"号池 {len(accs)} 个账号, 日期 {TODAY}, 平台: {', '.join(dailies)}")

    # 只对活跃账号签到/探活: pool(未售)/on_sale(在售). sold(已售)/disabled(停用) 停止每日任务
    ACTIVE = {"pool", "on_sale"}
    active = [a for a in accs if a.get("status") in ACTIVE]
    inactive = [a for a in accs if a.get("status") not in ACTIVE]
    if inactive:
        print(f"跳过 {len(inactive)} 个非活跃账号 (sold/disabled 等), 仅保留原状态回写")

    groups = {}
    for a in active:
        groups.setdefault(a.get("platform") or "aimagnet", []).append(a)

    accounts_out, signs, points, health = [], [], [], []
    err_logs = []          # 渠道报错 -> 上报 Worker
    for name, p in dailies.items():
        grp = groups.get(name, [])
        if not grp:
            print(f"== {p.label}: 无账号, 跳过 ==")
            continue
        print(f"== {p.label}: {len(grp)} 个账号 ==")
        try:
            o, s, pt, h = p.daily(grp, print)
        except Exception as e:
            o, s, pt, h = [], [], [], []
            print(f"== {p.label}: daily 整体异常: {str(e)[:120]}")
            err_logs.append({"platform": name, "category": "daily", "level": "error",
                             "message": f"daily整体异常:{str(e)[:300]}"})
        accounts_out += o; signs += s; points += pt; health += h
        for rec in h:
            if not rec.get("ok"):
                cat = "login" if "login" in str(rec.get("error") or "").lower() else "daily"
                err_logs.append({"platform": name, "category": cat, "level": "error",
                                 "message": f"account#{rec.get('account_id')}: {str(rec.get('error') or '')[:400]}"})

    # 其它平台账号原样回写 (仅保留花瓣/状态)
    known = {name for name in dailies}
    for name, grp in groups.items():
        if name in known:
            continue
        for a in grp:
            accounts_out.append({"id": a["id"], "platform": name, "email": a.get("email"),
                                 "nickname": a.get("nickname"), "password": a.get("password"),
                                 "email_password": a.get("email_password") or "", "user_id": a.get("user_id") or "",
                                 "registered_at": a.get("registered_at") or "", "petals": a.get("petals", 0),
                                 "stardust": a.get("stardust", 0), "status": a.get("status", "pool")})

    # 非活跃账号 (sold/disabled) 原样回写, 保持状态不变, 不签到探活
    for a in inactive:
        accounts_out.append({"id": a["id"], "platform": a.get("platform") or "aimagnet",
                             "email": a.get("email") or "", "nickname": a.get("nickname") or "",
                             "password": a.get("password") or "", "email_password": a.get("email_password") or "",
                             "user_id": a.get("user_id") or "",                              "registered_at": a.get("registered_at") or "",
                             "petals": a.get("petals", 0), "stardust": a.get("stardust", 0), "status": a.get("status", "pool")})

    body = {"accounts": accounts_out, "sign_records": signs, "points": points, "health": health}
    r = http("POST", f"{API}/api/chunshui/sync", body, token=ADMIN)
    print("同步:", r.status_code, r.text[:200])
    if err_logs:
        try:
            r2 = http("POST", f"{API}/api/channel-logs", {"logs": err_logs}, token=ADMIN)
            print("报错上报:", r2.status_code, r2.text[:120])
        except Exception as e:
            print("报错上报异常:", str(e)[:100])
    print(f"完成: 签到 {len(signs)}, 探活 {len(health)}, 报错上报 {len(err_logs)} 条")
    sys.exit(0)

if __name__ == "__main__":
    main()