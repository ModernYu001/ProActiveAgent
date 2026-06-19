#!/bin/bash
# ProActive 一键启动 (macOS 双击此文件即可)
# 首次会自动建虚拟环境+装依赖; 之后直接常驻盯梢。
cd "$(dirname "$0")" || exit 1
set -e

echo "▶ ProActive 启动中 …"

# 1) 虚拟环境 + 依赖 (仅首次)
if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境并安装依赖（约 1 分钟）…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

# 2) 配置文件 (缺失则用预填模板)
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env（含预填密钥）。如需改邮箱/Telegram，编辑 .env 后重启即可。"
fi

# 3) 常驻运行：按各话题间隔自动盯梢 + 每日自省
echo "✅ 开始盯梢。关闭此窗口即停止。"
exec ./.venv/bin/python run.py loop
