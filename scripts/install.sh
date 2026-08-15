#!/usr/bin/env bash
# vision-mcp 一键安装（macOS/Linux，自动判断系统，无需 Python）
# 用法: curl -fsSL https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.sh | bash
set -euo pipefail
REPO="LaconicChip/vision-mcp"

# 1) 安装位置（优先 ~/.local/bin，回退 ~/bin）
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR" 2>/dev/null || BIN_DIR="$HOME/bin"
mkdir -p "$BIN_DIR"
BIN="$BIN_DIR/vision-mcp"

# 2) 优先下载预编译二进制（无需 Python）
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="vision-mcp-Linux-x86_64" ;;
  Linux-aarch64) ASSET="vision-mcp-Linux-aarch64" ;;
  Darwin-arm64)  ASSET="vision-mcp-Darwin-arm64" ;;
  Darwin-x86_64) ASSET="vision-mcp-Darwin-x86_64" ;;
  *) ASSET="" ;;
esac

if [ -n "$ASSET" ]; then
  URL="https://github.com/$REPO/releases/latest/download/$ASSET"
  TMP_BIN="$(mktemp "$BIN_DIR/.vision-mcp.XXXXXX")"
  if curl -fsSL "$URL" -o "$TMP_BIN" 2>/dev/null; then
    chmod +x "$TMP_BIN"
    mv -f "$TMP_BIN" "$BIN"
    echo "✅ 已安装 $BIN（无需 Python）"
    # 重连终端，保证交互式填 key 可用（curl | bash 管道下 stdin 不是 tty）
    if [ -t 0 ]; then
      exec "$BIN" install
    elif exec "$BIN" install < /dev/tty 2>/dev/null; then
      :
    else
      echo "请运行以下命令完成配置："
      echo "  $BIN install"
    fi
    exit 0
  fi
  rm -f "$TMP_BIN"
  echo "（未找到预编译包，回退到 Python 方式...）"
fi

# 3) 回退：git + python（需要 Python）
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 "https://github.com/$REPO.git" "$TMP/vision-mcp"
cd "$TMP/vision-mcp"
python3 server.py install
