#!/usr/bin/env bash
# vision-mcp 一键安装（macOS/Linux）
# 用法: curl -fsSL https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.sh | bash -s codex
# 目标: codex | claude | cursor | all
set -euo pipefail
TARGET="${1:-codex}"
REPO="https://github.com/LaconicChip/vision-mcp.git"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> 下载 vision-mcp ..."
git clone --depth 1 "$REPO" "$TMP/vision-mcp"

echo "==> 安装并注册到 $TARGET ..."
cd "$TMP/vision-mcp"
python3 install.py --for "$TARGET"

echo ""
echo "✅ 完成。请编辑配置填写 API Key："
echo "   ${HOME}/.mcp-servers/vision-mcp/config.json"
echo "然后重启你的 Agent。"
