#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision-mcp 一键安装 / 注册辅助脚本（通用 MCP）。

用法：
  python3 install.py --for codex                # 安装并注册到 Codex
  python3 install.py --for claude               # 安装并注册到 Claude Desktop
  python3 install.py --for cursor               # 安装并注册到 Cursor
  python3 install.py --for all                  # 全部注册
  python3 install.py --print-clients            # 只打印各客户端配置
  python3 install.py --dest /path --no-register # 只复制，不注册
  python3 install.py --uninstall                # 卸载 + 回滚
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
DEST_DIR = Path.home() / ".mcp-servers" / "vision-mcp"
LIB_FILES = ("server.py", "config.example.json", "README.md", "LICENSE")

CODEX_TOML = Path.home() / ".codex" / "config.toml"
CLAUDE_JSON = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
CURSOR_JSON = Path.home() / ".cursor" / "mcp.json"

CODEX_BLOCK = """[mcp_servers.vision-mcp]
type = "stdio"
command = "python3"
args = ["{server_path}"]
startup_timeout_sec = 120
"""


def server_path(dest: Path) -> Path:
    return dest / "server.py"


# ---------- 复制 ----------

def copy_files(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in LIB_FILES:
        src = SOURCE / name
        if src.exists():
            shutil.copy2(src, dest / name)
            print(f"  ✓ 已复制 {name} -> {dest / name}")
    server = dest / "server.py"
    if not server.exists():
        print(f"  错误: 缺少 {server}", file=sys.stderr)


# ---------- 注册 ----------

def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-vision-mcp-{stamp}")
    shutil.copy2(path, backup)
    return backup


def _add_json_server(path: Path, server: Path) -> bool:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  警告: 无法解析 {path}: {e}", file=sys.stderr)
    servers = data.get("mcpServers", {})
    servers["vision-mcp"] = {"command": "python3", "args": [str(server)]}
    data["mcpServers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def register_codex(server: Path) -> None:
    if not CODEX_TOML.exists():
        print("  警告: 找不到 ~/.codex/config.toml，跳过 Codex 注册。", file=sys.stderr)
        return
    _backup(CODEX_TOML)
    text = CODEX_TOML.read_text(encoding="utf-8")
    block = CODEX_BLOCK.format(server_path=server)
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            h = st[1:-1].strip()
            if h == "mcp_servers.vision-mcp" or h.startswith("mcp_servers.vision-mcp."):
                start = i
                break
    if start is None:
        text = (text if text.endswith("\n") else text + "\n") + "\n" + block
    else:
        end = start + 1
        while end < len(lines) and not (lines[end].strip().startswith("[") and lines[end].strip().endswith("]")):
            end += 1
        tail = "".join(lines[end:])
        if not block.endswith("\n"):
            block += "\n"
        if tail and not tail.startswith("\n"):
            block += "\n"
        text = "".join(lines[:start]) + block + tail
    CODEX_TOML.write_text(text, encoding="utf-8")
    print(f"  ✓ 已注册 Codex -> [mcp_servers.vision-mcp] = {server}")


def register_claude(server: Path) -> None:
    _backup(CLAUDE_JSON)
    _add_json_server(CLAUDE_JSON, server)
    print(f"  ✓ 已注册 Claude Desktop -> {CLAUDE_JSON}")


def register_cursor(server: Path) -> None:
    _backup(CURSOR_JSON)
    _add_json_server(CURSOR_JSON, server)
    print(f"  ✓ 已注册 Cursor -> {CURSOR_JSON}")


# ---------- 打印示例 ----------

def print_snippets(server: Path) -> None:
    print("将 server.py 的绝对路径替换进如下配置：\n")
    print("### codex  (~/.codex/config.toml)")
    print(CODEX_BLOCK.format(server_path=server).rstrip() + "\n")
    print("### claude_desktop  (claude_desktop_config.json)")
    print(json.dumps({"mcpServers": {"vision-mcp": {"command": "python3", "args": [str(server)]}}},
                     ensure_ascii=False, indent=2) + "\n")
    print("### cursor  (~/.cursor/mcp.json)")
    print(json.dumps({"mcpServers": {"vision-mcp": {"command": "python3", "args": [str(server)]}}},
                     ensure_ascii=False, indent=2) + "\n")


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="vision-mcp 一键安装/注册")
    parser.add_argument("--for", dest="clients", choices=["codex", "claude", "cursor", "all"], default="codex",
                        help="注册到哪个客户端（默认 codex）")
    parser.add_argument("--dest", default=str(DEST_DIR), help="安装目标目录")
    parser.add_argument("--no-register", action="store_true", help="只复制不注册")
    parser.add_argument("--print-clients", action="store_true", help="只打印各客户端配置")
    parser.add_argument("--uninstall", action="store_true", help="卸载并回滚")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dest = Path(os.path.expanduser(args.dest))
    server = server_path(dest)

    if args.print_clients:
        print_snippets(server)
        return 0
    if args.uninstall:
        if args.dry_run:
            print(f"[dry-run] 将删除 {dest}")
            return 0
        shutil.rmtree(dest, ignore_errors=True)
        print(f"已删除 {dest}")
        return 0
    if args.dry_run:
        print(f"[dry-run] 将安装到 {dest}")
        print(f"[dry-run] 将注册到: {args.clients}")
        print_snippets(server)
        return 0

    print(f"安装到: {dest}")
    copy_files(dest)
    if args.no_register:
        print("已复制（跳过注册）。")
        return 0

    targets = ["codex", "claude", "cursor"] if args.clients == "all" else [args.clients]
    for t in targets:
        if t == "codex":
            register_codex(server)
        elif t == "claude":
            register_claude(server)
        elif t == "cursor":
            register_cursor(server)
    print("完成。重启对应的 Agent 后即可使用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
