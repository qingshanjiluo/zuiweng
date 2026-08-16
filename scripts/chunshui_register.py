#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · GitHub Actions 批量注册春水号 -> 同步到 Worker
env: ZUIWENG_API / ADMIN_TOKEN / COUNT (每轮注册数)
注意: aimagnet register 20s/IP 冷却 + mail.tm 收码 ~30-60s, 每个账号约 1-2 分钟
"""
import os, sys, io, time, datetime, requests
from aimagnet_client import MailTM, Aimagnet, rand_name
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = os.environ.get("ZUIWENG_API", "https://zuiweng-api.sifangzhiji.workers.dev")
ADMIN = os.environ.get("ADMIN_TOKEN", "")
COUNT = int(os.environ.get("COUNT", "5"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36")

def http(method, url, json=None, token=None):
    h = {"user-agent": UA, "content-type": "application/json", "accept": "application/json"}
    if token:
        h["authorization"] = f"Bearer {token}"
    return requests.request(method, url, json=json, headers=h, timeout=40)

def register_one():
    """注册一个账号, 返回 (account_dict) 或 None"""
    mt = MailTM()
    am = Aimagnet()
    email, epwd = mt.create()
    print(f"  邮箱 {email}")
    r = am.register_start(email)
    if r.status_code != 200:
        print(f"  register/start {r.status_code}: {r.text[:120]}")
        return None
    code = mt.wait_code(email, epwd, timeout=90)
    if not code:
        print("  收码超时")
        return None
    print(f"  验证码 {code}")
    r = am.register_complete(email, code)
    if r.status_code != 200:
        print(f"  register/complete {r.status_code}: {r.text[:120]}")
        return None
    try:
        user, token = am.login(email, am.pwd)
    except Exception as e:
        print(f"  login 失败: {str(e)[:100]}")
        return None
    petals = 0
    try:
        petals = int(am.balance(user["id"], token).get("petals") or 0)
    except Exception:
        pass
    return {
        "nickname": user.get("nickname") or rand_name(),
        "password": am.pwd, "email": email, "email_password": epwd,
        "user_id": user["id"], "registered_at": str(user.get("createdAt") or ""),
        "petals": petals, "status": "pool",
    }

def main():
    if not ADMIN:
        print("缺少 ADMIN_TOKEN"); sys.exit(1)
    print(f"本轮计划注册 {COUNT} 个账号")
    accounts = []
    for i in range(COUNT):
        print(f"[{i+1}/{COUNT}] 注册中...")
        try:
            acc = register_one()
            if acc:
                accounts.append(acc)
                print(f"  OK {acc['nickname']} petals={acc['petals']}")
        except Exception as e:
            print(f"  异常: {str(e)[:100]}")
        time.sleep(25)  # register 20s/IP 冷却
    if not accounts:
        print("全部失败"); sys.exit(1)
    r = http("POST", f"{API}/api/chunshui/sync", {"accounts": accounts}, token=ADMIN)
    print("同步:", r.status_code, r.text[:200])
    print(f"完成: 新注册并入库 {len(accounts)} 个")
    sys.exit(0)

if __name__ == "__main__":
    main()