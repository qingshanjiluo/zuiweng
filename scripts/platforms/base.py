#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""醉翁亭 · 多平台适配器基类
每个酒馆平台实现一个适配器, 提供统一的注册/每日任务接口.
统一账号字段 (account dict):
  platform, nickname, password, email, email_password, user_id,
  registered_at, petals, status
"""
import json, os, importlib


class PlatformBase:
    # 子类必须覆盖
    name = ""    # 平台标识, 与 D1 chunshui_accounts.platform 一致
    label = ""   # 中文名

    def register(self, log):
        """注册一个账号, 返回统一 account dict; 失败返回 None"""
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
        mods[name] = inst
    return mods


def all_accounts_fields():
    """sync 到 Worker 所需的完整字段列表 (防止缺字段导致的 undefined 问题)"""
    return ["platform", "nickname", "password", "email", "email_password",
            "user_id", "registered_at", "petals", "status"]