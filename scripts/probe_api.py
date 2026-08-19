# -*- coding: utf-8 -*-
"""探测 Worker API 中可查询"某日签到记录"的端点, 用于实现补签检测."""
import io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests

API = 'https://zuiweng-api.sifangzhiji.workers.dev'
tok = requests.post(API + '/api/auth/login', json={'username': 'admin', 'password': 'Pipi20100817'}, timeout=30).json()
tok = tok.get('data', {}).get('token')
h = {'Authorization': 'Bearer ' + tok, 'user-agent': 'probe/1.0'}
today = '2026-08-19'

cands = [
    '/api/chunshui/sign-records?date=' + today,
    '/api/admin/chunshui/sign-records?date=' + today,
    '/api/admin/chunshui/signs?date=' + today,
    '/api/chunshui/signs?date=' + today,
    '/api/chunshui/sign-records?date=' + today + '&platform=missai',
    '/api/admin/chunshui/sign-records?date=' + today + '&platform=missai',
    '/api/admin/chunshui/accounts?limit=2',
    '/api/admin/chunshui/stats?platform=missai',
]
for c in cands:
    try:
        r = requests.get(API + c, headers=h, timeout=30)
        body = r.text[:150].replace('\n', ' ')
        print(f'{r.status_code} {c} => {body}')
    except Exception as e:
        print(f'ERR {c} => {str(e)[:80]}')