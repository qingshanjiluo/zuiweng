# 醉翁亭
春水号池自动化 (GitHub Actions + Cloudflare)。

## 目录
- `scripts/` 自动化脚本 (注册/签到/探活)
- `.github/workflows/` GitHub Actions 定时任务

## Secrets
| Secret | 用途 |
|--------|------|
| `ZUIWENG_API` | Worker 同步 API 地址 |
| `ADMIN_TOKEN` | Worker 同步鉴权 |