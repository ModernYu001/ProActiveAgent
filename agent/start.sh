#!/bin/bash
# ProActive 启动脚本 (Linux / 手动运行)
# 用法: ./start.sh [loop|once|digest|review|quota]   默认 loop
cd "$(dirname "$0")" || exit 1
set -e

MODE="${1:-loop}"

if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

[ -f .env ] || cp .env.example .env

exec ./.venv/bin/python run.py "$MODE"
