from __future__ import annotations
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision-mcp 安装/卸载/注册辅助脚本（通用 MCP）。

用法：
  python3 install.py                # 安装到默认位置并注册到 Codex
  python3 install.py --dest /path   # 只复制到指定目录，不注册
  python3 install.py --print-clients  # 打印 Codex / Claude Desktop / Cursor 注册配置
  python3 install.py --uninstall    # 卸载 Codex 安装并回滚 config.toml
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
DEST_DIR = Path.home() / ".codex" / "mcp-servers" / "vision-mcp"
CONFIG_TOML = Path.home() / ".codex" / "config.toml"
SERVER_REL = "server.py"

NEW_BLOCK = """[mcp_servers.vision-mcp]
type = "stdio"
command = "python3"
args = ["{server_path}"]
startup_timeout_sec = 120
"""

CLIENT_SNIPPETS = {
    "codex": """# ~/.codex/config.toml
[mcp_servers.vision-mcp]
type = "stdio"
command = "python3"
args = ["{server_path}"]
startup_timeout_sec = 120""",
    "claude_desktop": """// claude_desktop_config.json
{{
  "mcpServers": {{
    "vision-mcp": {{
      "command": "python3",
      "args": ["{server_path}"]
    }}
  }}
}}""",
    "cursor": """# ~/.cursor/mcp.json
{{
  "mcpServers": {{
    "vision-mcp": {{
      "command": "python3",
      "args": ["{server_path}"]
    }}
  }}
}}""",
    "generic": """# 通用 stdio MCP 客户端
command: python3
args: ["{server_path}"]
env:
  GLM_MCP_API_KEY: "你的火山引擎Key"   # 可选
  GLM_API_KEY: "你的智谱Key"           # 可选
  AGNES_API_KEY: "你的AgnesKey"        # 可选""",
}


def print_snippets(server_path: Path) -> None:
    print("将 server.py 的绝对路径替换进如下配置：\n")
    for name, snippet in CLIENT_SNIPPETS.items():
        print(f"### {name}\n{snippet.format(server_path=server_path)}\n")


def backup_config() -> Path | None:
    if not CONFIG_TOML.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_TOML.with_name(f"config.toml.bak-vision-mcp-{stamp}")
    shutil.copy2(CONFIG_TOML, backup)
    return backup


def replace_section(text: str, new_block: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            header = stripped[1:-1].strip()
            if header == "mcp_servers.vision-mcp" or header.startswith("mcp_servers.vision-mcp."):
                start = i
                break
    if start is None:
        return (text if text.endswith("\n") else text + "\n") + "\n" + new_block, True
    end = start + 1
    while end < len(lines) and not (lines[end].strip().startswith("[") and lines[end].strip().endswith("]")):
        end += 1
    tail = "".join(lines[end:])
    if not new_block.endswith("\n"):
        new_block += "\n"
    if tail and not tail.startswith("\n"):
        new_block += "\n"
    return "".join(lines[:start]) + new_block + tail, True


def install(dest: Path, register: bool, dry_run: bool) -> int:
    print(f"安装目标: {dest}")
    if dry_run:
        print("[dry-run] 将复制:")
        for name in ("server.py", "config.example.json", "README.md", "LICENSE"):
            print(f"  {name} -> {dest / name}")
        print("\n注册配置：#")
        print(NEW_BLOCK.format(server_path=dest / SERVER_REL))
        print("\n其他客户端注册示例：")
        print_snippets(dest / SERVER_REL)
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    for name in ("server.py", "config.example.json", "README.md", "LICENSE"):
        src = SOURCE / name
        if src.exists():
            shutil.copy2(src, dest / name)
            print(f"已复制: {name}")

    server_path = dest / SERVER_REL
    if register:
        if not CONFIG_TOML.exists():
            print(f"警告: 找不到 {CONFIG_TOML}，跳过 Codex 注册。")
        else:
            backup = backup_config()
            print(f"已备份配置: {backup}")
            text = CONFIG_TOML.read_text(encoding="utf-8")
            updated, _ = replace_section(text, NEW_BLOCK.format(server_path=server_path))
            CONFIG_TOML.write_text(updated, encoding="utf-8")
            print(f"已注册 [mcp_servers.vision-mcp] -> {server_path}")
    print("\n其他客户端注册示例：")
    print_snippets(server_path)
    print("安装完成。")
    return 0


def uninstall(dest: Path, dry_run: bool) -> int:
    backups = sorted(CONFIG_TOML.parent.glob("config.toml.bak-vision-mcp-*")) if CONFIG_TOML.exists() else []
    if dry_run:
        print(f"[dry-run] 将删除 {dest}")
        if backups:
            print(f"[dry-run] 将用 {backups[-1]} 恢复 {CONFIG_TOML}")
        return 0
    if backups:
        shutil.copy2(backups[-1], CONFIG_TOML)
        print(f"已恢复 {CONFIG_TOML}（来自 {backups[-1]}）")
    shutil.rmtree(dest, ignore_errors=True)
    print(f"已删除 {dest}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="vision-mcp 安装/卸载/注册")
    parser.add_argument("--dest", default=str(DEST_DIR), help="安装目标目录")
    parser.add_argument("--no-register", action="store_true", help="只复制，不写 Codex config.toml")
    parser.add_argument("--print-clients", action="store_true", help="只打印各客户端注册示例")
    parser.add_argument("--uninstall", action="store_true", help="卸载并回滚")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dest = Path(os.path.expanduser(args.dest))
    if args.print_clients:
        print_snippets(dest / SERVER_REL)
        return 0
    if args.uninstall:
        return uninstall(dest, args.dry_run)
    return install(dest, register=not args.no_register, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
