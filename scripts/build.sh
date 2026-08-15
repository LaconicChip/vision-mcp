#!/usr/bin/env bash
# Build a single-file executable (no Python needed by end users).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --onefile --name vision-mcp server.py

echo ""
echo "✅ 构建完成：dist/vision-mcp"
echo "   注册 MCP 时把 args 指向这个二进制，用户无需安装 Python。"
