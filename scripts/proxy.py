#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机场订阅代理管理: 下载订阅 -> 生成精简配置 -> 启动/停止 mihomo -> 验证连通
env: SUB_URL / PROXY_PORT(默认7890) / PROXY_DIR(默认系统temp/mihomo)
命令:
  python scripts/proxy.py start    # 启动并等待就绪
  python scripts/proxy.py stop     # 停止
  python scripts/proxy.py check    # 验证出口IP
启动后输出: PROXY_URL=http://127.0.0.1:PORT (供脚本读取)
"""
import os, sys, io, time, platform, subprocess, json, tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SUB_URL = os.environ.get("SUB_URL", "")
PORT = int(os.environ.get("PROXY_PORT", "7890"))
DIR = os.environ.get("PROXY_DIR") or os.path.join(tempfile.gettempdir(), "mihomo")
GH = "https://github.com/MetaCubeX/mihomo/releases/latest/download"
try:
    import requests
except Exception:
    requests = None

PROXY = f"http://127.0.0.1:{PORT}"


def mihomo_name():
    m = platform.system().lower()
    a = platform.machine().lower()
    if m == "windows":
        arch = "amd64" if a in ("amd64", "x86_64") else ("arm64" if "arm" in a else "386")
        return f"mihomo-windows-{arch}-compatible.exe"
    if m == "darwin":
        return f"mihomo-darwin-{'arm64' if a == 'arm64' else 'amd64'}"
    arch = "amd64" if a in ("amd64", "x86_64") else ("arm64" if "arm" in a else "386")
    return f"mihomo-linux-{arch}"


def ensure_mihomo():
    exe = os.path.join(DIR, mihomo_name())
    if os.path.exists(exe):
        return exe
    os.makedirs(DIR, exist_ok=True)
    # 通过 GitHub API 找带版本号的资产 (mihomo 资产名含版本号, latest/download 不适用)
    api = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
    if requests:
        r = requests.get(api, timeout=60, headers={"user-agent": "curl/8"})
        r.raise_for_status()
        assets = r.json().get("assets") or []
    else:
        import urllib.request, json
        assets = json.load(urllib.request.urlopen(api, timeout=60)).get("assets") or []
    base = mihomo_name()
    if base.endswith(".exe"):
        want = base[:-4]  # 资产名: mihomo-windows-amd64-compatible-<ver>.zip
    else:
        want = base       # 资产名: mihomo-linux-amd64-<ver>.gz
    cand = [a for a in assets if a["name"].startswith(want) and a["name"].endswith((".zip", ".gz"))]
    if not cand:
        print(f"未找到 mihomo 资产 {want}"); sys.exit(1)
    url = cand[0]["browser_download_url"]
    print(f"下载 mihomo: {cand[0]['name']}")
    if requests:
        raw = requests.get(url, timeout=180).content
    else:
        import urllib.request
        raw = urllib.request.urlopen(url, timeout=180).read()
    if base.endswith(".exe"):
        import zipfile, io
        z = zipfile.ZipFile(io.BytesIO(raw))
        z.extract(base, DIR)
    else:
        import gzip
        open(exe, "wb").write(gzip.decompress(raw))
        os.chmod(exe, 0o755)
    return exe


def build_config():
    if not SUB_URL:
        print("缺少 SUB_URL"); sys.exit(1)
    print("下载订阅...")
    if requests:
        r = requests.get(SUB_URL, timeout=30, headers={"user-agent": "clash-verge/v1.3.8"})
        r.raise_for_status()
        text = r.text
    else:
        import urllib.request
        text = urllib.request.urlopen(SUB_URL, timeout=30).read().decode("utf-8", "replace")
    try:
        import yaml
        d = yaml.safe_load(text)
    except Exception:
        print("订阅不是 YAML (可能 base64 订阅), 尝试 base64 解码")
        import base64
        padded = text.strip() + "=" * (-len(text.strip()) % 4)
        text = base64.b64decode(padded).decode("utf-8", "replace")
        d = yaml.safe_load(text)
    proxies = d.get("proxies") or []
    if len(proxies) < 5:
        print(f"订阅无效(机场限流/套餐超限): 仅 {len(proxies)} 节点, 可能返回提示页")
        sys.exit(1)
    fake = [p for p in proxies if str(p.get("server", "")).startswith("127.")]
    if fake:
        print(f"订阅被机场限流(返回提示页/假节点): 请检查机场设备数是否超限")
        sys.exit(1)
    names = [p["name"] for p in proxies]
    cfg = {
        "mixed-port": PORT,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "warning",
        "proxies": proxies,
        "proxy-groups": [{
            "name": "PROXY", "type": "load-balance",
            "proxies": names, "url": "http://www.gstatic.com/generate_204", "interval": 300,
            "strategy": os.environ.get("PROXY_STRATEGY", "round-robin"),
        }],
        # 分流: Worker API/mail.tm 等直连, 其余平台走代理
        "rules": [f"DOMAIN-SUFFIX,{d.strip()},DIRECT"
                  for d in os.environ.get("PROXY_DIRECT_DOMAINS", "workers.dev,mail.tm").split(",")
                  if d.strip()] + ["MATCH,PROXY"],
    }
    with open(os.path.join(DIR, "config.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    print(f"配置生成: {len(proxies)} 节点")


def start():
    os.makedirs(DIR, exist_ok=True)
    build_config()
    exe = ensure_mihomo()
    proc = subprocess.Popen([exe, "-d", DIR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 等待端口就绪
    import socket
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            s.close()
            break
        except Exception:
            time.sleep(1)
    else:
        print("mihomo 启动超时"); sys.exit(1)
    print(f"mihomo 就绪 {PROXY}")
    print(f"PROXY_URL={PROXY}")


def stop():
    m = mihomo_name()
    if platform.system().lower() == "windows":
        subprocess.run(["taskkill", "/F", "/IM", m], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", m], capture_output=True)
    print("mihomo 已停止")


def check():
    if requests is None:
        print("需要 requests"); sys.exit(1)
    try:
        r = requests.get("https://api.ipify.org", proxies={"http": PROXY, "https": PROXY}, timeout=30)
        print(f"出口 IP: {r.text}")
        return r.text
    except Exception as e:
        print(f"代理不通: {str(e)[:150]}")
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "check":
        check()
    else:
        print("用法: start|stop|check")