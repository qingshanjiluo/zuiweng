#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · 多平台批量注册 -> 同步到 Worker
env: ZUIWENG_API / ADMIN_TOKEN / COUNT (每平台每轮注册数)
配置: scripts/platforms.json (register=true 的平台会被注册)
"""
import os, sys, io, time, random, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from platforms import load_config, build_platforms

API = os.environ.get("ZUIWENG_API", "https://zuiweng-api.sifangzhiji.workers.dev")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
COUNT = int(os.environ.get("COUNT", "5"))
SHARDS = int(os.environ.get("SHARDS", "1"))     # 并行 job 总数
SHARD = int(os.environ.get("SHARD", "0"))       # 当前 job 序号
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36")

def http(method, url, json=None, token=None):
    h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
    if token:
        h["authorization"] = f"Bearer {token}"
    return requests.request(method, url, json=json, headers=h, timeout=40)

def main():
    if not ADMIN:
        print("缺少 ADMIN_TOKEN"); sys.exit(1)
    config = load_config()
    plats = build_platforms(config)
    regs = {n: p for n, p in plats.items() if getattr(p, "register_enabled", False)}
    if not regs:
        print("无启用的注册平台 (platforms.json)"); sys.exit(1)
    per = max(1, (COUNT + SHARDS - 1) // SHARDS)
    print(f"本轮注册: " + ", ".join(f"{p.label} x{COUNT}(shard {SHARD}/{SHARDS}: {per}个)" for p in regs.values()))
    accounts = []
    for name, p in regs.items():
        print(f"== {p.label} ({name}) ==")
        got = 0
        for i in range(per):
            print(f"[{i+1}/{per}] 注册中...")
            acc = None
            for attempt in range(2):
                try:
                    acc = p.register(print)
                    if acc:
                        break
                except Exception as e:
                    print(f"  异常: {str(e)[:100]}")
            if acc:
                accounts.append(acc)
                got += 1
                print(f"  OK {acc['nickname']} petals={acc['petals']}")
            # 随机人类节奏间隔, 降低批量特征
            time.sleep(getattr(p, "register_interval", 25) * random.uniform(0.8, 1.6))
        print(f"{p.label}: 新注册 {got}/{per}")
    if not accounts:
        print("全部失败"); sys.exit(1)
    r = http("POST", f"{API}/api/chunshui/sync", {"accounts": accounts}, token=ADMIN)
    print("同步:", r.status_code, r.text[:200])
    print(f"完成: 新注册并入库 {len(accounts)} 个")
    sys.exit(0)

if __name__ == "__main__":
    main()