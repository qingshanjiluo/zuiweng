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
    if not dailies:
        print("无启用的每日平台 (platforms.json)"); sys.exit(1)

    r = http("GET", f"{API}/api/admin/chunshui/accounts", token=ADMIN)
    if r.status_code != 200:
        print("拉号池失败", r.status_code, r.text[:200]); sys.exit(1)
    accs = r.json()["data"]["accounts"]
    print(f"号池 {len(accs)} 个账号, 日期 {TODAY}, 平台: {', '.join(dailies)}")

    groups = {}
    for a in accs:
        groups.setdefault(a.get("platform") or "aimagnet", []).append(a)

    accounts_out, signs, points, health = [], [], [], []
    for name, p in dailies.items():
        grp = groups.get(name, [])
        if not grp:
            print(f"== {p.label}: 无账号, 跳过 ==")
            continue
        print(f"== {p.label}: {len(grp)} 个账号 ==")
        o, s, pt, h = p.daily(grp, print)
        accounts_out += o; signs += s; points += pt; health += h

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
                                 "status": a.get("status", "pool")})

    body = {"accounts": accounts_out, "sign_records": signs, "points": points, "health": health}
    r = http("POST", f"{API}/api/chunshui/sync", body, token=ADMIN)
    print("同步:", r.status_code, r.text[:200])
    print(f"完成: 签到 {len(signs)}, 探活 {len(health)}")
    sys.exit(0)

if __name__ == "__main__":
    main()