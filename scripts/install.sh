#!/usr/bin/env bash
# vision-mcp 一键安装（macOS/Linux，自动判断系统）
# 用法: curl -fsSL https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.sh | bash
set -euo pipefail
REPO="LaconicChip/vision-mcp"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) 优先下载预编译二进制（无需 Python）
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="vision-mcp-Linux-x86_64" ;;
  Linux-aarch64) ASSET="vision-mcp-Linux-aarch64" ;;
  Darwin-arm64)  ASSET="vision-mcp-Darwin-arm64" ;;
  Darwin-x86_64) ASSET="vision-mcp-Darwin-x86_64" ;;
  *) ASSET="" ;;
esac

if [ -n "$ASSET" ]; then
  URL="https://github.com/$REPO/releases/latest/download/$ASSET"
  if curl -fsSL "$URL" -o "$TMP/vision-mcp" 2>/dev/null; then
    chmod +x "$TMP/vision-mcp"
    exec "$TMP/vision-mcp" install
  fi
  echo "（未找到预编译包，回退到 Python 方式...）"
fi

# 2) 回退：git + python
git clone --depth 1 "https://github.com/$REPO.git" "$TMP/vision-mcp"
cd "$TMP/vision-mcp"
python3 server.py install
