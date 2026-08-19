#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · 补签机制: 对比各平台今日已签到数(signedToday)与活跃账号数,
发现漏签(不足)则对对应平台重跑 daily 补签.
daily 幂等: 已签到账号返回 ALREADY 不会重复签到, 因此补跑安全.
env: ZUIWENG_API / ADMIN_TOKEN / PLATFORM(可选, 只补指定平台)
"""
import os, sys, io, time, datetime, requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from platforms import load_config, build_platforms

API = os.environ.get("ZUIWENG_API", "https://zuiweng-api.sifangzhiji.workers.dev")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
PLATFORM = os.environ.get("PLATFORM", "")
BATCH = int(os.environ.get("BATCH", "400"))
TOPUP_TIMEOUT = int(os.environ.get("TOPUP_PLATFORM_TIMEOUT", "600"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36")
TODAY = datetime.datetime.utcnow().strftime("%Y-%m-%d")


def http(method, url, json=None, token=None):
    h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
    if token:
        h["authorization"] = f"Bearer {token}"
    return requests.request(method, url, json=json, headers=h, timeout=30)


def fetch_all_accounts():
    seen, off = set(), 0
    out = []
    while True:
        r = http("GET", f"{API}/api/admin/chunshui/accounts?limit=5000&offset={off}", token=ADMIN)
        if r.status_code != 200:
            print("拉号池失败", r.status_code, r.text[:200]); sys.exit(1)
        page = r.json()["data"]["accounts"]
        if not page:
            break
        for a in page:
            if a["id"] not in seen:
                out.append(a); seen.add(a["id"])
        if len(page) < 5000:
            break
        off += 5000
    return out


def main():
    if not ADMIN:
        print("缺少 ADMIN_TOKEN"); sys.exit(1)
    plats = build_platforms(load_config())
    dailies = {n: p for n, p in plats.items() if getattr(p, "daily_enabled", False)}
    if PLATFORM:
        dailies = {n: p for n, p in dailies.items() if n == PLATFORM}
    accs = fetch_all_accounts()
    ACTIVE = {"pool", "on_sale"}
    active = [a for a in accs if a.get("status") in ACTIVE]
    groups = {}
    for a in active:
        groups.setdefault(a.get("platform") or "aimagnet", []).append(a)
    print(f"号池 {len(accs)} 个账号, 活跃 {len(active)}, 日期 {TODAY}")

    for name, grp in groups.items():
        if name not in dailies or not grp:
            continue
        try:
            st = http("GET", f"{API}/api/admin/chunshui/stats?platform={name}", token=ADMIN).json()
            signed = (st.get("data") or {}).get("signedToday") or 0
        except Exception as e:
            print(f"== {name}: 查 stats 失败 {str(e)[:80]}")
            continue
        missing = len(grp) - signed
        if missing <= 0:
            print(f"== {name}: 活跃 {len(grp)} signedToday {signed} 已全覆盖, 跳过")
            continue
        print(f"== {name}: 活跃 {len(grp)} signedToday {signed} 缺 {missing}, 补签 ==")
        accounts_out, signs, points, health = [], [], [], []
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(dailies[name].daily, grp, print)
                try:
                    o, s, pt, h = fut.result(timeout=TOPUP_TIMEOUT)
                except FutureTimeout:
                    o, s, pt, h = [], [], [], []
                    print(f"== {name}: 补签超时({TOPUP_TIMEOUT}s), 放弃本次补签 ==")
        except Exception as e:
            o, s, pt, h = [], [], [], []
            print(f"== {name}: 补签整体异常: {str(e)[:120]}")
        accounts_out += o; signs += s; points += pt; health += h
        for i in range(0, len(accounts_out), BATCH):
            body = {"accounts": accounts_out[i:i + BATCH],
                    "sign_records": signs[i:i + BATCH] if i < len(signs) else [],
                    "points": points[i:i + BATCH] if i < len(points) else [],
                    "health": health[i:i + BATCH] if i < len(health) else []}
            try:
                rr = http("POST", f"{API}/api/chunshui/sync", body, token=ADMIN)
                print(f"同步({len(body['accounts'])}账号/{len(body['sign_records'])}签到): {rr.status_code} {rr.text[:100]}")
            except Exception as e:
                print(f"同步异常: {str(e)[:120]}")
        print(f"== {name}: 补签完成, 新增签到 {len(signs)} ==")
    print("补签检查完成")
    sys.exit(0)


if __name__ == "__main__":
    main()