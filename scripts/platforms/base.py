#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · 多平台适配器基类
每个酒馆平台实现一个适配器, 提供统一的注册/每日任务接口.
统一账号字段 (account dict):
  platform, nickname, password, email, email_password, user_id,
  registered_at, petals, status
"""
import json, os, importlib, random, re, string, time, threading

_NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "网名库.txt")

# 重名/占用 关键词, 用于识别"换名重试"
_DUP_KEYS = ("已存在", "已被注册", "已被使用", "重复", "占用", "已注册", "exists", "already registered",
             "already taken", "duplicate", "dup", "registered")


class NicknameGen:
    """统一昵称生成: 网名库词 + 自动序号(数字) + 日期 + 随机英文字母
    shard 偏移保证并行 job 序号段不冲突 (SHARD/SHARDS 环境变量)."""
    def __init__(self, shard=0):
        self.seq = int(shard) * 200000
        self.words = self._load()
        self._lock = threading.Lock()

    def _load(self):
        try:
            with open(_NAMES_FILE, encoding="utf-8") as f:
                ws = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                if ws:
                    return ws
        except Exception:
            pass
        return ["醉", "亭", "墨", "砚", "竹", "梅", "雪", "月"]

    def next(self, platform=""):
        with self._lock:
            self.seq += 1
            n = self.seq
        word = random.choice(self.words)
        ts = time.strftime("%y%m%d")
        letters = "".join(random.choices(string.ascii_lowercase, k=2))
        prefix = ""
        if platform:
            # 平台标识取前2个英文字母/拼音, 便于肉眼识别归属
            p = re.sub(r"[^a-zA-Z]", "", platform)[:2].lower()
            if p:
                prefix = p
        return f"{word}{n}{ts}{prefix}{letters}"


def is_dup_error(msg):
    """判断错误文本是否属于"昵称/用户名重复" """
    m = str(msg or "").lower()
    return any(k in m for k in _DUP_KEYS)


class PlatformBase:
    # 子类必须覆盖
    name = ""    # 平台标识, 与 D1 chunshui_accounts.platform 一致
    label = ""   # 中文名

    def __init__(self):
        # 注册/签到失败原因回传 (供 driver 上报渠道错误)
        self.last_error = ""

    def register(self, log):
        """注册一个账号, 返回统一 account dict; 失败返回 None (self.last_error 记录原因)"""
        raise NotImplementedError

    def daily(self, accounts, log):
        """对一批该平台账号执行 登录/签到/探活/取余额
        返回 (accounts_out, signs, points, health)
          accounts_out: 更新后的账号列表 (需含 id/email/nickname/password/.../petals/status)
          signs:  [{account_id,date,status,reward}]
          points:[{account_id,date,petals}]
          health:[{account_id,ok,error,petals}]
        """
        raise NotImplementedError


def load_config(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platforms.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_platforms(config=None):
    """根据配置实例化所有已启用平台适配器 -> {name: adapter}"""
    config = config or load_config()
    shard = int(os.environ.get("SHARD", "0"))
    gen = NicknameGen(shard)
    mods = {}
    for name, cfg in config.items():
        if not cfg.get("enabled", True):
            continue
        try:
            mod = importlib.import_module(cfg["module"])
        except Exception as e:
            print(f"[platforms] 加载 {name} 失败: {e}")
            continue
        cls = getattr(mod, cfg.get("class", "Platform"))
        inst = cls()
        inst.name = name
        inst.label = cfg.get("label", name)
        inst.register_enabled = cfg.get("register", False)
        inst.daily_enabled = cfg.get("daily", False)
        inst.register_interval = cfg.get("register_interval", 25)
        inst.gen = gen           # 共享名字生成器, 保证批次内/跨平台序号唯一
        mods[name] = inst
    return mods


def all_accounts_fields():
    """sync 到 Worker 所需的完整字段列表 (防止缺字段导致的 undefined 问题)"""
    return ["platform", "nickname", "password", "email", "email_password",
            "user_id", "registered_at", "petals", "status"]