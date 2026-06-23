#!/bin/bash
# ProActive 单次运行 (macOS 双击此文件 = 只跑一轮就结束)
# 与 start.command 的区别: 这个跑一次 run.py once 就停, 不常驻。
cd "$(dirname "$0")" || exit 1
set -e

echo "▶ ProActive 单次运行 …"

# 虚拟环境 + 依赖 (仅首次)
if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境并安装依赖（约 1 分钟）…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

# 配置文件 (缺失则用预填模板)
[ -f .env ] || cp .env.example .env

# 只跑一轮
./.venv/bin/python run.py once

echo ""
echo "✅ 本轮完成。可关闭此窗口。"
