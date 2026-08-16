#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 PoC: 验证 GitHub Actions runner 出口 IP 能否访问 aimagnet.vip 和 mail.tm
输出: runner IP / aimagnet 探活 / mail.tm 可达 / register.start 接受度 / mail.tm 建邮箱"""
import sys, io, requests, random, string, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/150.0.0.0 Safari/537.36")

try:
    ip = requests.get("https://api.ipify.org", timeout=15).text.strip()
    print("[IP] runner 出口:", ip)
except Exception as e:
    print("[IP] 获取失败:", str(e)[:80])

try:
    r = requests.get("https://aimagnet.vip/", headers={"user-agent": UA}, timeout=20)
    print(f"[aimagnet] GET / -> {r.status_code} | {r.text[:60]}")
except Exception as e:
    print("[aimagnet] GET / 异常:", str(e)[:100])

try:
    r = requests.get("https://api.mail.tm/domains", headers={"user-agent": UA}, timeout=20)
    print(f"[mail.tm] domains -> {r.status_code} | {r.text[:120]}")
except Exception as e:
    print("[mail.tm] domains 异常:", str(e)[:100])

# aimagnet register/start (仅测 1 次; runner IP 若被拦则 403/400)
try:
    email = "poc" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)) + "@emalupe.com"
    user = "poc" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))
    r = requests.post("https://aimagnet.vip/v1/auth/register/start",
                      json={"email": email, "password": "Hh12345678!", "nickname": user,
                            "contentPreferences": ["male", "female", "all"], "contentPreferenceConfirmed": True},
                      headers={**{"user-agent": UA, "origin": "https://aimagnet.vip", "referer": "https://aimagnet.vip/auth",
                                 "content-type": "application/json", "accept": "application/json"}},
                      timeout=30)
    print(f"[aimagnet] register/start -> {r.status_code} | {r.text[:160]}")
except Exception as e:
    print("[aimagnet] register/start 异常:", str(e)[:100])

# mail.tm 建邮箱
try:
    email = "poc" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + "@emalupe.com"
    r = requests.post("https://api.mail.tm/accounts",
                      json={"address": email, "password": "Poc12345678!"},
                      headers={"user-agent": UA, "content-type": "application/json"}, timeout=25)
    print(f"[mail.tm] create -> {r.status_code} | {r.text[:120]}")
except Exception as e:
    print("[mail.tm] create 异常:", str(e)[:100])