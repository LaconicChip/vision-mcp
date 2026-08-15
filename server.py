#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vision-mcp
================
零第三方依赖的 MCP 图像理解服务器（stdio）。

路由优先级：
  1. race：五模型并发竞速，首个有效结果获胜（glm / glm-thinking / glm-4.6v / agnes×2）
  2. fallback：五模型全部失败/超时后，降级到用户自定义的保底多模态模型
  3. OCR：仍失败且需要文字提取时，尝试 系统原生OCR（macOS Vision / Windows OCR / Tesseract）
  4. 全部失败 → 明确报错并返回完整尝试记录

配置：config.json（支持 // 和 # 注释），支持热重载。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVER_NAME = "vision-mcp"
SERVER_VERSION = "1.2.0"
PROTOCOL_VERSION = "2024-11-05"
IS_FROZEN = bool(getattr(sys, "frozen", False))


def _base_dir() -> Path:
    """二进制/源码所在目录：frozen 用二进制自身路径，源码用 server.py 所在目录。"""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
DEFAULT_CONFIG = BASE_DIR / "config.json"

DEFAULT_PROMPT = (
    "请详细描述这张图片的内容，包括画面中的文字、物体、界面元素、数据、代码和可能的含义。"
    "如果这是截图，请重点提取其中的关键信息。"
)
DEFAULT_CONFIG_TEXT = "{\n  // =============================================================\n  // vision-mcp 配置（JSONC：支持 // 和 # 注释，保存后自动热重载）\n  // 复制/编辑 config.json 后填写你的 API Key。\n  // =============================================================\n\n  // ---- 默认提示词（可改）------------------------------------------\n  \"default_prompt\": \"请详细描述这张图片的内容，包括画面中的文字、物体、界面元素、数据、代码和可能的含义。如果这是截图，请重点提取其中的关键信息。\",\n\n  // ---- 路由顺序 ----------------------------------------------------\n  // 1) race：免费竞速池，多个模型并发，首个有效结果获胜\n  // 2) fallback：免费竞速池全部失败/超时后，自动降级到用户自定义保底模型\n  \"routing\": {\n    \"race\": [\n      \"glm\",               // glm-4v-flash\n      \"glm-thinking\",      // glm-4.1v-thinking-flash\n      \"glm-4.6v-flash\",    // glm-4.6v-flash（⚠️ 不稳定，可能限流/慢）\n      \"agnes-2.5-flash\",   // agnes-2.5-flash\n      \"agnes-2.0-flash\"    // agnes-2.0-flash\n    ],\n    \"fallback\": [\n      \"custom-1\"           // ← 用户自定义保底多模态模型（免费池全失败时自动降级）\n    ]\n  },\n\n  // ---- 免费竞速池通道：每个都是 OpenAI 兼容 chat/completions ------\n  // api_key（字面量）优先；没填则用 api_key_env 指向的环境变量。\n  \"channels\": [\n    {\n      \"id\": \"glm\",\n      \"provider\": \"zhipu\",\n      \"base_url\": \"https://open.bigmodel.cn/api/paas/v4/chat/completions\",\n      \"model\": \"glm-4v-flash\",\n      \"api_key\": \"\",                          // ← 智谱 Key（GLM_API_KEY）\n      \"api_key_env\": \"GLM_API_KEY\",\n      \"timeout_ms\": 90000,\n      \"max_tokens\": 2048\n    },\n    {\n      \"id\": \"glm-thinking\",\n      \"provider\": \"zhipu\",\n      \"base_url\": \"https://open.bigmodel.cn/api/paas/v4/chat/completions\",\n      \"model\": \"glm-4.1v-thinking-flash\",\n      \"api_key\": \"\",                          // 与 glm 同一个智谱 Key\n      \"api_key_env\": \"GLM_API_KEY\",\n      \"timeout_ms\": 90000,\n      \"max_tokens\": 2048\n    },\n    {\n      \"id\": \"glm-4.6v-flash\",\n      \"provider\": \"zhipu\",\n      \"base_url\": \"https://open.bigmodel.cn/api/paas/v4/chat/completions\",\n      \"model\": \"glm-4.6v-flash\",\n      \"api_key\": \"\",                          // 与 glm 同一个智谱 Key\n      \"api_key_env\": \"GLM_API_KEY\",\n      \"timeout_ms\": 120000,\n      \"max_tokens\": 2048,\n      \"note\": \"glm-4.6v-flash 可用但不稳定：可能 429 限流或响应很慢（实测约 24s），保留作补充\"\n    },\n    {\n      \"id\": \"agnes-2.5-flash\",\n      \"provider\": \"agnes\",\n      \"base_url\": \"https://apihub.agnes-ai.com/v1/chat/completions\",\n      \"model\": \"agnes-2.5-flash\",\n      \"api_key\": \"\",                          // ← Agnes Key（AGNES_API_KEY）\n      \"api_key_env\": \"AGNES_API_KEY\",\n      \"timeout_ms\": 90000,\n      \"max_tokens\": 2048\n    },\n    {\n      \"id\": \"agnes-2.0-flash\",\n      \"provider\": \"agnes\",\n      \"base_url\": \"https://apihub.agnes-ai.com/v1/chat/completions\",\n      \"model\": \"agnes-2.0-flash\",\n      \"api_key\": \"\",                          // 与 agnes-2.5-flash 同一个 key\n      \"api_key_env\": \"AGNES_API_KEY\",\n      \"timeout_ms\": 90000,\n      \"max_tokens\": 2048\n    },\n\n    // ---- 用户自定义保底通道（免费竞速池全部失败后自动降级到这里）----\n    // 自行填写你的多模态模型地址、模型名和 key；也可从环境变量读取。\n    {\n      \"id\": \"custom-1\",\n      \"provider\": \"custom\",\n      \"base_url\": \"\",                          // ← 你的保底多模态模型 chat/completions 地址\n      \"model\": \"\",                             // ← 你的保底模型名\n      \"api_key\": \"\",                           // ← 你的保底模型 key（或留空用下面环境变量）\n      \"api_key_env\": \"VISION_CUSTOM_API_KEY\",\n      \"timeout_ms\": 120000,\n      \"max_tokens\": 4096\n    }\n  ],\n\n  // 限额：单图大小、超时、默认 max_tokens\n  \"limits\": {\n    \"max_file_bytes\": 15728640,   // 15 MB\n    \"timeout_ms\": 90000,\n    \"max_tokens\": 1024\n  },\n\n  // 缓存：按图片内容哈希缓存结果，避免重复调用\n  \"storage\": {\n    \"cache_enabled\": true,\n    \"cache_dir\": \"~/.cache/vision-mcp\",\n    \"cache_ttl_seconds\": 604800   // 7 天\n  },\n\n  // OCR（可选）：纯文字提取时兜底（系统原生，本地离线，不上云）\n  \"ocr\": {\n    \"system\": {\n      \"enabled\": true,\n      \"languages\": \"zh-Hans,en-US\"\n    },\n    \"tesseract\": {\n      \"enabled\": true,\n      \"command\": \"tesseract\",\n      \"languages\": \"chi_sim+eng\"\n    }\n  },\n\n  // 文档解析（可选）：PDF/Word/PPT 走 MinerU\n  \"document\": {\n    \"mineru\": {\n      \"enabled\": false,\n      \"command\": \"mineru-open-api\",\n      \"mode\": \"flash\"\n    }\n  }\n}\n"

USER_CONFIG_DIR = Path.home() / ".config" / "vision-mcp"
USER_CONFIG = USER_CONFIG_DIR / "config.json"


def resolve_config_path() -> Path:
    """配置路径优先级：DS_VISION_CONFIG > ~/.config/vision-mcp/config.json > 包目录 config.json"""
    env = os.environ.get("DS_VISION_CONFIG")
    if env:
        return Path(env)
    if USER_CONFIG.exists():
        return USER_CONFIG
    pkg = BASE_DIR / "config.json"
    if pkg.exists():
        return pkg
    return USER_CONFIG


def init_config() -> Path:
    """生成用户级配置（首次运行 / vision-mcp init）。"""
    target = Path(os.environ.get("DS_VISION_CONFIG") or USER_CONFIG)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return target


CODEX_TOML = Path.home() / ".codex" / "config.toml"
CLAUDE_JSON = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
CURSOR_JSON = Path.home() / ".cursor" / "mcp.json"


def _ask(label: str, default: str = "") -> str:
    try:
        if sys.stdin.isatty():
            return input(f"{label} [{default}]: ").strip() or default
    except Exception:
        pass
    return default


def _set_keys_in_place(path: Path, mapping: list[tuple[str, str]]) -> None:
    """按通道顺序把 api_key 占位替换成用户 key，保留 JSONC 注释。"""
    text = path.read_text(encoding="utf-8")
    marker = '"api_key": ""'
    for _, key in mapping:
        if not key:
            continue
        i = text.find(marker)
        if i < 0:
            break
        text = text[:i] + f'"api_key": "{key}"' + text[i + len(marker):]
    path.write_text(text, encoding="utf-8")


def server_command() -> tuple[str, list[str]]:
    """注册 MCP 时的启动命令：frozen 直接用二进制自身（免 Python），源码用 python3 server.py。"""
    if IS_FROZEN:
        return (str(Path(sys.executable).resolve()), [])
    return ("python3", [str(Path(__file__).resolve())])


def _add_json_server(path: Path) -> None:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cmd, args = server_command()
    servers = data.setdefault("mcpServers", {})
    servers["vision-mcp"] = {"command": cmd, "args": args}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _register_codex(cmd: str, args: list[str]) -> None:
    """把 vision-mcp 段写入/替换进 ~/.codex/config.toml（幂等，不重复追加）。"""
    block = (f'[mcp_servers.vision-mcp]\ntype = "stdio"\n'
             f'command = "{cmd}"\nargs = {json.dumps(args)}\nstartup_timeout_sec = 120\n')
    text = CODEX_TOML.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().startswith("[mcp_servers.vision-mcp") and ln.strip().endswith("]")), None)
    if start is None:
        CODEX_TOML.write_text((text if text.endswith("\n") else text + "\n") + "\n" + block, encoding="utf-8")
        return
    end = start + 1
    while end < len(lines) and not (lines[end].strip().startswith("[") and lines[end].strip().endswith("]")):
        end += 1
    CODEX_TOML.write_text("".join(lines[:start]) + block + "".join(lines[end:]), encoding="utf-8")


def cmd_install() -> int:
    """交互式一键安装配置：填 key + 自动注册到已发现的 Agent。"""
    cfg = init_config()
    print(f"配置: {cfg}")

    keys = [
        ("glm", "智谱 Key（glm / glm-thinking / glm-4.6v）"),
        ("agnes", "Agnes Key（agnes-2.5 / agnes-2.0）"),
        ("custom-1", "保底多模态模型 Key（可选，回车跳过）"),
    ]
    mapping: list[tuple[str, str]] = []
    for i, (k, label) in enumerate(keys):
        val = _ask(f"{label}", "")
        if k == "custom-1" and not val:
            continue
        mapping.append((k, val))
    # 模板里 api_key 占位顺序：glm, glm-thinking, glm-4.6v, agnes-2.5, agnes-2.0, custom-1
    order = ["glm", "glm", "glm", "agnes", "agnes"]
    if any(k == "custom-1" for k, _ in mapping):
        order.append("custom-1")
    filled = []
    for i, tag in enumerate(order):
        key = next((v for k, v in mapping if k == tag), "")
        filled.append((tag, key))
    _set_keys_in_place(cfg, filled)

    cmd, args = server_command()
    print(f"\n注册命令: {cmd}" + (f" {' '.join(args)}" if args else ""))

    registered: list[str] = []
    if CODEX_TOML.exists():
        _register_codex(cmd, args)
        registered.append("Codex")
        print("  ✓ 已注册 Codex → ~/.codex/config.toml")
    for label, path in (("Claude Desktop", CLAUDE_JSON), ("Cursor", CURSOR_JSON)):
        if path.exists():
            _add_json_server(path)
            registered.append(label)
            print(f"  ✓ 已注册 {label} → {path}")
    if not registered:
        print("\n未检测到 Codex / Claude Desktop / Cursor 配置，请手动注册：")
        print(f"  command = {cmd}")
        print(f"  args    = {json.dumps(args)}")

    print("\n✅ 完成。重启对应 Agent 后即可使用。")
    return 0


IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}


def mask_key(key: str) -> str:
    if not key:
        return "(未设置)"
    return key[:4] + "****" + key[-4:] if len(key) > 8 else key[:2] + "****"


def error_text(e: Exception) -> str:
    return str(e).replace("\r", " ").replace("\n", " ")[:500]


def strip_json_comments(text: str) -> str:
    """去掉 JSONC 注释（//、/* */、#），保留字符串内容，兼容纯 JSON。"""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and text[i:i + 2] == "/*":
            i = text.find("*/", i + 2)
            i = n if i < 0 else i + 2
            continue
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c); i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class Config:
    """读取 config.json（支持注释）+ 环境变量，按 mtime 热重载。"""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else resolve_config_path()
        self._mtime = -1.0
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        raw: dict = {}
        if self.path.exists():
            try:
                raw = json.loads(strip_json_comments(self.path.read_text(encoding="utf-8")))
                if not isinstance(raw, dict):
                    raw = {}
            except Exception as e:
                print(f"[{SERVER_NAME}] 警告: 读取 {self.path} 失败: {e}", file=sys.stderr)
        self._data = normalize(raw)

    def get(self) -> dict:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime != self._mtime or not self._data:
            self._mtime = mtime
            self._load()
        return self._data


def normalize(raw: dict) -> dict:
    """归一化配置。channels 完全来自 config；不合成任何内置提供商。"""
    channels = raw.get("channels") or []
    if not isinstance(channels, list):
        channels = []
    routing = raw.get("routing") or {}
    race = [str(x) for x in routing.get("race", []) if isinstance(x, (str, int))]
    fallback = [str(x) for x in routing.get("fallback", []) if isinstance(x, (str, int))]
    if not race and not fallback:
        race = [ch.get("id") for ch in channels if isinstance(ch, dict) and ch.get("id")]

    limits = raw.get("limits") or {}
    storage = raw.get("storage") or {}
    ocr = raw.get("ocr") or {}
    document = raw.get("document") or {}
    sys_ocr = ocr.get("system") or {}
    tess = ocr.get("tesseract") or {}
    mineru = document.get("mineru") or {}

    cache_dir = os.path.expanduser(os.path.expandvars(storage.get("cache_dir") or "~/.cache/vision-mcp"))
    return {
        "default_prompt": raw.get("default_prompt") or DEFAULT_PROMPT,
        "channels": channels,
        "race": race,
        "fallback": fallback,
        "max_tokens": int(limits.get("max_tokens", 1024)),
        "timeout_ms": int(limits.get("timeout_ms", 90000)),
        "max_file_bytes": int(limits.get("max_file_bytes", 15 * 1024 * 1024)),
        "cache": {
            "enabled": bool(storage.get("cache_enabled", True)),
            "directory": cache_dir,
            "ttl_seconds": int(storage.get("cache_ttl_seconds", 7 * 24 * 60 * 60)),
        },
        "ocr": {
            "system": {"enabled": bool(sys_ocr.get("enabled", True)),
                       "languages": sys_ocr.get("languages", "")},
            "tesseract": {"enabled": bool(tess.get("enabled", True)),
                          "command": tess.get("command", "tesseract"),
                          "languages": tess.get("languages", "eng")},
        },
        "document": {"mineru": {"enabled": bool(mineru.get("enabled", False)),
                                "command": mineru.get("command", "mineru-open-api"),
                                "mode": mineru.get("mode", "flash")}},
    }


# ---------------------------------------------------------------------------
# 图片与模型调用
# ---------------------------------------------------------------------------

def read_image_bytes(image: str) -> tuple[str, str]:
    """把 image 参数解析成 (mime, base64)。支持本地路径/URL/data URI/裸 base64。"""
    if not image or not isinstance(image, str):
        raise ValueError("image 不能为空")
    image = image.strip()

    if image.startswith("data:"):
        head, _, b64 = image.partition(",")
        return head.split(";")[0][5:] or "image/png", b64.strip()

    if image.startswith(("http://", "https://")):
        ctx = ssl.create_default_context()
        req = urllib.request.Request(image, headers={"User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read()
        return resp.headers.get_content_type() or "image/png", base64.b64encode(raw).decode("ascii")

    path = os.path.expanduser(image)
    if os.path.isfile(path):
        with open(path, "rb") as f:
            raw = f.read()
        mime, _ = mimetypes.guess_type(path)
        return mime or "image/png", base64.b64encode(raw).decode("ascii")

    try:
        decoded = base64.b64decode(image, validate=True)
        known = (decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8")
                 or decoded.startswith(b"GIF87a") or decoded.startswith(b"GIF89a")
                 or (decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP"))
        if not known and len(decoded) < 128:
            raise ValueError
        mime = ("image/png" if decoded.startswith(b"\x89PNG")
                else "image/jpeg" if decoded.startswith(b"\xff\xd8")
                else "image/gif" if decoded.startswith(b"GIF")
                else "image/webp" if decoded.startswith(b"RIFF")
                else "image/png")
        return mime, image
    except Exception:
        raise ValueError("无法解析 image：既不是本地文件，也不是 http(s) URL、data URI 或有效 base64")


def _ext_for_mime(mime: str) -> str:
    return {v: k for k, v in IMAGE_MIME.items()}.get(mime, ".png")


def call_channel(channel: dict, data_url: str, prompt: str, max_tokens: int,
                 timeout_ms: int, temperature: float | None = None) -> dict:
    """调用单个 OpenAI 兼容通道，返回 {content, latency_ms}。"""
    base = (channel.get("base_url") or "").strip().rstrip("/")
    if base and not base.endswith("/chat/completions"):
        base += "/chat/completions"
    api_key = channel.get("_api_key") or ""
    if not api_key and not channel.get("api_key_optional"):
        raise RuntimeError(f"channel {channel.get('id')} 缺少 API Key")

    payload = {
        "model": channel.get("model") or "",
        "temperature": temperature if temperature is not None else float(channel.get("temperature", 0.2)),
        "max_tokens": int(max_tokens or channel.get("max_tokens") or 1024),
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update({str(k): str(v) for k, v in (channel.get("headers") or {}).items()})

    req = urllib.request.Request(base, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0, context=ssl.create_default_context()) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:600]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}")

    content = body.get("choices", [{}])[0].get("message", {}).get("content")
    if isinstance(content, list):
        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("text"))
    if not content or not str(content).strip():
        raise RuntimeError("返回内容为空")
    return {"content": str(content), "latency_ms": int((time.time() - started) * 1000)}


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _cache_key(image_sha: str, prompt: str, channel: dict, max_tokens: int) -> str:
    return hashlib.sha256(json.dumps(
        [1, image_sha, prompt, channel["id"], channel.get("model"), channel.get("base_url"), int(max_tokens)],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_cache(config: dict, key: str) -> dict | None:
    cache = config.get("cache") or {}
    if not cache.get("enabled"):
        return None
    path = Path(cache.get("directory", "")).expanduser() / f"{key}.json"
    try:
        if time.time() - path.stat().st_mtime > int(cache.get("ttl_seconds", 604800)):
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(config: dict, key: str, value: dict) -> None:
    cache = config.get("cache") or {}
    if not cache.get("enabled"):
        return
    directory = Path(cache.get("directory", "")).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f"{key}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, directory / f"{key}.json")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# OCR / 文档
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout_ms: int) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_ms / 1000.0)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 退出 {proc.returncode}: {(proc.stderr or '')[-500:]}")
    return proc.stdout


_MACOS_OCR_JS = r"""ObjC.import("Vision"); ObjC.import("Foundation");
function run(argv) {
  const url = $.NSURL.fileURLWithPath(argv[0]);
  const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $.NSDictionary.alloc.init);
  const req = $.VNRecognizeTextRequest.alloc.init;
  const langs = (argv.length > 1 && argv[1]) ? $.NSArray.arrayWithArray(argv[1].split(",")) : $.NSArray.arrayWithArray(["zh-Hans", "en-US"]);
  req.recognitionLanguages = langs;
  req.recognitionLevel = argv.length > 2 ? parseInt(argv[2]) : 0;
  const err = Ref();
  const ok = handler.performRequestsError($.NSArray.arrayWithObject(req), err);
  if (!ok) { return "ERR:" + (err[0] ? err[0].description.js : "perform failed"); }
  const results = req.results;
  const out = [];
  for (let i = 0; i < results.count; i++) {
    const cands = results.objectAtIndex(i).topCandidates(1);
    if (cands.count > 0) { out.push(cands.objectAtIndex(0).string.js); }
  }
  return out.join("\n");
}"""


def macos_vision_ocr(image: bytes, accurate: bool, languages: str) -> dict:
    """macOS 系统原生 OCR：Apple Vision 框架（JXA 脚本，零依赖、本地离线）。"""
    with tempfile.TemporaryDirectory(prefix="ds-vision-ocr-") as tmp:
        img_path = os.path.join(tmp, "input.png")
        open(img_path, "wb").write(image)
        js_path = os.path.join(tmp, "ocr.js")
        open(js_path, "w", encoding="utf-8").write(_MACOS_OCR_JS)
        level = 0 if accurate else 1  # accurate / fast
        proc = subprocess.run(["osascript", "-l", "JavaScript", js_path, img_path, languages, str(level)],
                              capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"macOS Vision OCR 失败: {(proc.stderr or proc.stdout).strip()[-300:]}")
        text = proc.stdout.strip()
    if not text or text.startswith("ERR:"):
        raise RuntimeError(text or "macOS Vision OCR 未识别到文字")
    return {"content": text, "tool_used": "vision:macos", "confidence": "high",
            "metadata": {"local": True, "engine": "Apple Vision"}, "latency_ms": 0}


_WINDOWS_OCR_PS1 = r"""param([string]$Path, [string]$Lang = "")
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
function Await($WinRtTask, $ResultType) {
  $m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  })[0]
  $net = $m.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
  $net.Wait(-1) | Out-Null
  return $net.Result
}
$file   = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
# 语言：config 里是 "zh-Hans,en-US"，按逗号逐个尝试；全部失败退回系统用户语言
$engine = $null
if ($Lang) {
  foreach ($tag in ($Lang.Split(",") | ForEach-Object { $_.Trim() })) {
    try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag)) }
    catch { $engine = $null }
    if ($engine) { break }
  }
}
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Error "系统无可用 OCR 语言"; exit 1 }
$res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
$res.Lines | ForEach-Object { $_.Text }"""


def windows_ocr(image: bytes, languages: str) -> dict:
    """Windows 系统原生 OCR：Windows.Media.Ocr（PowerShell WinRT，本地离线）。"""
    with tempfile.TemporaryDirectory(prefix="ds-vision-ocr-") as tmp:
        img_path = os.path.join(tmp, "input.png")
        open(img_path, "wb").write(image)
        ps_path = os.path.join(tmp, "ocr.ps1")
        open(ps_path, "w", encoding="utf-8").write(_WINDOWS_OCR_PS1)
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", ps_path, "-Path", img_path, "-Lang", languages],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"Windows OCR 失败: {(proc.stderr or proc.stdout).strip()[-300:]}")
        text = proc.stdout.strip()
    if not text:
        raise RuntimeError("Windows OCR 未识别到文字")
    return {"content": text, "tool_used": "ocr:windows", "confidence": "high",
            "metadata": {"local": True, "engine": "Windows.Media.Ocr"}, "latency_ms": 0}


def system_ocr(config: dict, image: bytes, mime: str, accurate: bool) -> dict:
    """系统原生 OCR，自动识别平台：macOS Vision / Windows OCR / Linux Tesseract。"""
    sysname = platform.system()
    ocr_cfg = config["ocr"]
    if sysname == "Darwin":
        if not ocr_cfg["system"]["enabled"]:
            raise RuntimeError("系统 OCR 未启用")
        return macos_vision_ocr(image, accurate, ocr_cfg["system"]["languages"])
    if sysname == "Windows":
        if not ocr_cfg["system"]["enabled"]:
            raise RuntimeError("系统 OCR 未启用")
        return windows_ocr(image, ocr_cfg["system"]["languages"])
    return tesseract_ocr(config, image, mime)  # Linux 及其他平台


def tesseract_ocr(config: dict, image: bytes, mime: str) -> dict:
    ocr = config["ocr"]["tesseract"]
    if not ocr["enabled"]:
        raise RuntimeError("Tesseract 未启用")
    if shutil.which(ocr["command"]) is None:
        raise RuntimeError(f"找不到命令 {ocr['command']}")
    with tempfile.TemporaryDirectory(prefix="ds-vision-ocr-") as tmp:
        path = os.path.join(tmp, "input" + _ext_for_mime(mime))
        open(path, "wb").write(image)
        text = _run([ocr["command"], path, "stdout", "-l", ocr["languages"]],
                    int(config.get("timeout_ms", 90000))).strip()
    if not text:
        raise RuntimeError("Tesseract 未识别到文字")
    return {"content": text, "tool_used": f"tesseract:{ocr['languages']}", "confidence": "medium", "metadata": {"local": True}, "latency_ms": 0}


def _find_md(root: str) -> str | None:
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        if entry.is_dir():
            found = _find_md(entry.path)
            if found:
                return found
        elif entry.is_file() and entry.name.lower().endswith(".md"):
            return entry.path
    return None


def mineru_parse(config: dict, file: str) -> dict:
    doc = config["document"]["mineru"]
    if not doc["enabled"]:
        raise RuntimeError("MinerU 未启用")
    out = os.path.join(tempfile.gettempdir(), f"ds-vision-mineru-{_sha256(file.encode())[:12]}")
    os.makedirs(out, exist_ok=True)
    md = _find_md(out)
    if md is None:
        args = (["flash-extract", file, "-o", out] if doc["mode"] == "flash"
                else ["extract", file, "-o", out, "-f", "md"])
        _run([doc["command"]] + args, int(config.get("timeout_ms", 90000)))
        md = _find_md(out)
    if md is None:
        raise RuntimeError("MinerU 未生成 Markdown")
    text = open(md, encoding="utf-8").read().strip()
    if not text:
        raise RuntimeError("MinerU 输出为空")
    return {"content": text, "tool_used": f"mineru:{doc['mode']}", "confidence": "high", "metadata": {"chars": len(text)}, "latency_ms": 0}


# ---------------------------------------------------------------------------
# 路由：race → fallback → OCR
# ---------------------------------------------------------------------------

class VisionRouter:
    def __init__(self, config_provider):
        self._provider = config_provider

    @property
    def config(self) -> dict:
        return self._provider()

    def _api_key(self, ch: dict) -> str:
        if ch.get("api_key"):
            return ch["api_key"]
        return os.environ.get(ch.get("api_key_env") or "VISION_API_KEY", "") or ""

    def _ready(self, ids: list[str]) -> list[dict]:
        by_id = {c.get("id"): c for c in self.config["channels"] if isinstance(c, dict)}
        out = []
        for cid in ids:
            ch = by_id.get(cid)
            if ch is None or ch.get("enabled") is False:
                continue
            key = self._api_key(ch)
            if not key and not ch.get("api_key_optional"):
                continue
            ch = dict(ch); ch["_api_key"] = key
            out.append(ch)
        return out

    def _call(self, ch: dict, data_url: str, prompt: str, max_tokens: int, no_cache: bool) -> dict:
        image_sha = _sha256(base64.b64decode(data_url.split(",", 1)[1]))
        key = _cache_key(image_sha, prompt, ch, max_tokens)
        if not no_cache:
            hit = read_cache(self.config, key)
            if hit is not None:
                hit.setdefault("metadata", {})["cached"] = True
                return hit
        result = call_channel(ch, data_url, prompt, max_tokens,
                              int(ch.get("timeout_ms") or self.config["timeout_ms"]),
                              temperature=ch.get("temperature"))
        env = {"task_type": "image_reasoning", "tool_used": f"{ch['id']}:{ch.get('model')}",
               "confidence": "high", "result": result["content"],
               "metadata": {"channel": ch["id"], "model": ch.get("model"), "image_sha256": image_sha,
                            "latency_ms": result["latency_ms"], "cached": False}}
        if not no_cache:
            write_cache(self.config, key, env)
        return env

    def _race(self, channels: list[dict], data_url: str, prompt: str,
              max_tokens: int, no_cache: bool) -> tuple[dict | None, list[dict]]:
        """并发竞速：首个成功立即返回；全部失败立即返回。"""
        attempts, holder, lock = [], {}, threading.Lock()
        settled, pending = threading.Event(), len(channels)

        def work(ch):
            nonlocal pending
            started = time.time()
            try:
                env = self._call(ch, data_url, prompt, max_tokens, no_cache)
                with lock:
                    if not holder:
                        holder["env"] = env
                        settled.set()
                    attempts.append({"channel": ch["id"], "ok": True,
                                     "latency_ms": int((time.time() - started) * 1000)})
            except Exception as e:
                with lock:
                    attempts.append({"channel": ch["id"], "ok": False,
                                     "latency_ms": int((time.time() - started) * 1000), "error": error_text(e)})
            finally:
                with lock:
                    pending -= 1
                    if pending <= 0:
                        settled.set()

        threads = [threading.Thread(target=work, args=(c,), daemon=True) for c in channels]
        for t in threads:
            t.start()
        settled.wait(timeout=max(1.0, self.config.get("timeout_ms", 90000) / 1000.0 + 5))
        return holder.get("env"), attempts

    def route_image(self, data_url: str, prompt: str, intent: str,
                    complex: bool, accurate_ocr: bool, no_cache: bool,
                    max_tokens: int | None = None) -> dict:
        """路由：五模型 race → fallback(用户自定义保底模型) → OCR → 报错。"""
        config = self.config
        image = base64.b64decode(data_url.split(",", 1)[1])
        if len(image) > config["max_file_bytes"]:
            raise RuntimeError(f"图片超过大小限制 ({len(image)} > {config['max_file_bytes']})")

        attempts: list[dict] = []
        max_tokens = int(max_tokens or (max(2048, config["max_tokens"]) if complex else config["max_tokens"]))

        # 1) 五模型并发竞速（显式 ocr 意图直接走本地 OCR，不调云端）
        if intent != "ocr":
            race = self._ready(config.get("race", []))
            if race:
                env, race_attempts = self._race(race, data_url, prompt, max_tokens, no_cache)
                attempts.extend(race_attempts)
                if env:
                    env.setdefault("metadata", {})["race"] = {"mode": "first-success", "attempts": race_attempts}
                    env["metadata"]["attempts"] = attempts
                    return env

        # 2) 竞速全部失败才走 fallback（用户自定义兜底；显式 ocr 意图跳过）
        if intent != "ocr":
            for cid in config.get("fallback", []):
                for ch in self._ready([cid]):
                    started = time.time()
                    try:
                        env = self._call(ch, data_url, prompt, max_tokens, no_cache)
                        env.setdefault("metadata", {})["attempts"] = attempts
                        return env
                    except Exception as e:
                        attempts.append({"channel": cid, "ok": False,
                                         "latency_ms": int((time.time() - started) * 1000), "error": error_text(e)})

        # 3) 后续兜底：OCR（系统原生，自动识别平台）
        if intent in ("auto", "ocr") or accurate_ocr:
            mime = data_url.split(";")[0][5:]
            ocr_tools = [("system", lambda: system_ocr(config, image, mime, accurate_ocr))]
            if config["ocr"]["tesseract"]["enabled"]:
                ocr_tools.append(("tesseract", lambda: tesseract_ocr(config, image, mime)))
            for tool, fn in ocr_tools:
                try:
                    result = fn()
                    result.setdefault("metadata", {})["attempts"] = attempts
                    return result
                except Exception as e:
                    attempts.append({"tool": tool, "error": error_text(e)})

        raise RuntimeError(f"没有视觉路由成功: {json.dumps(attempts, ensure_ascii=False)}")

    def analyze_file(self, path: str, prompt: str, intent: str, complex: bool,
                     accurate_ocr: bool, no_cache: bool, max_tokens: int | None = None) -> dict:
        config = self.config
        if os.path.getsize(path) > config["max_file_bytes"]:
            raise RuntimeError(f"文件超过大小限制")
        ext = os.path.splitext(path)[1].lower()
        if intent == "auto":
            intent = ("document" if ext in DOCUMENT_EXTENSIONS
                      else "ocr" if (accurate_ocr or "ocr" in prompt.lower() or "识别" in prompt or "提取文字" in prompt)
                      else "reason")
        if intent == "document":
            try:
                return mineru_parse(config, path)
            except Exception:
                if ext not in IMAGE_MIME:
                    raise
        with open(path, "rb") as f:
            raw = f.read()
        mime = IMAGE_MIME.get(ext, "image/png")
        return self.route_image(f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                                prompt, "reason" if intent == "document" else intent, complex, accurate_ocr, no_cache, max_tokens)


# ---------------------------------------------------------------------------
# MCP 协议与工具
# ---------------------------------------------------------------------------

def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(msg_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": value}


def tool_text(msg_id, text: str, is_error: bool = False) -> dict:
    return result(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class _MemoryConfig:
    """不落盘的内联配置：满足 .get()/.path 接口，供零配置模式使用。"""

    def __init__(self, data: dict):
        self._data = data
        self.path = Path("(inline)")

    def get(self) -> dict:
        return self._data


_HOLDER = {"config": None}


def get_config() -> Config:
    if _HOLDER["config"] is None:
        _HOLDER["config"] = Config()
    return _HOLDER["config"]


def _router() -> VisionRouter:
    cfg = get_config()
    return VisionRouter(cfg.get)


TOOLS = [
    {"name": "understand_image",
     "description": "调用视觉模型理解图片，返回纯文本。支持五模型并发竞速，首个有效结果获胜；全部失败后降级火山引擎。截图/上传图片/界面截图/报错弹窗等需要看图时使用。",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string", "description": "本地绝对路径 / http(s) URL / data URI / 裸 base64"},
         "prompt": {"type": "string", "description": "指令，默认用配置中的 default_prompt"},
         "intent": {"type": "string", "enum": ["auto", "reason", "ocr", "document"], "description": "路由意图"},
         "complex": {"type": "boolean", "description": "复杂图片用更大输出预算"},
         "accurate_ocr": {"type": "boolean", "description": "优先高精度 OCR"},
         "no_cache": {"type": "boolean", "description": "绕过缓存"},
         "max_tokens": {"type": "integer", "description": "覆盖 max_tokens"}},
         "required": ["image"]}},
    {"name": "vision_analyze",
     "description": "与 understand_image 相同，但返回结构化 JSON 信封（tool_used/confidence/metadata/竞速记录）。",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string", "description": "本地绝对路径 / http(s) URL / data URI / 裸 base64"},
         "prompt": {"type": "string", "description": "指令"},
         "intent": {"type": "string", "enum": ["auto", "reason", "ocr", "document"]},
         "complex": {"type": "boolean"}, "accurate_ocr": {"type": "boolean"},
         "no_cache": {"type": "boolean"}, "max_tokens": {"type": "integer"}},
         "required": ["image"]}},
    {"name": "vision_config", "description": "查看当前生效的模型/地址/打码 key。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "vision_status", "description": "查看路由/通道可用性/缓存/OCR 状态（不泄露 key）。",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _run_tool(name: str, args: dict) -> str:
    router = _router()
    if name == "understand_image":
        mime, b64 = read_image_bytes(args["image"])
        prompt = (args.get("prompt") or "").strip() or router.config["default_prompt"]
        env = router.route_image(f"data:{mime};base64,{b64}", prompt, args.get("intent", "auto"),
                                 bool(args.get("complex")), bool(args.get("accurate_ocr")),
                                 bool(args.get("no_cache")), max_tokens=args.get("max_tokens"))
        return env.get("result") or env.get("content", "")
    if name == "vision_analyze":
        mime, b64 = read_image_bytes(args["image"])
        prompt = (args.get("prompt") or "").strip() or router.config["default_prompt"]
        env = router.route_image(f"data:{mime};base64,{b64}", prompt, args.get("intent", "auto"),
                                 bool(args.get("complex")), bool(args.get("accurate_ocr")),
                                 bool(args.get("no_cache")), max_tokens=args.get("max_tokens"))
        return json.dumps(env, ensure_ascii=False, indent=2)
    if name == "vision_config":
        cfg = router.config
        lines = ["当前视觉模型配置："]
        for ch in cfg["channels"]:
            lines.append(f"  channel : {ch.get('id')}  model={ch.get('model')}  base_url={ch.get('base_url')}  api_key={mask_key(router._api_key(ch))}")
        return "\n".join(lines)
    if name == "vision_status":
        cfg = router.config
        lines = [f"vision-mcp 视觉状态\n  配置  : {get_config().path}",
                 f"  路由  : race = {' + '.join(cfg['race']) or '(空)'} | fallback = {' -> '.join(cfg['fallback']) or '(空)'}",
                 f"  缓存  : {'on' if cfg['cache']['enabled'] else 'off'} -> {cfg['cache']['directory']}",
                 "  通道:"]
        for ch in cfg["channels"]:
            ready = bool(router._api_key(ch)) or ch.get("api_key_optional")
            state = "disabled" if ch.get("enabled") is False else ("ready" if ready else f"missing {ch.get('api_key_env')}")
            note = ("  ⚠️不稳定" if ch.get("id") == "glm-4.6v-flash" else "")
            lines.append(f"    - {ch.get('id')}: {ch.get('model')} [{state}]{note}")
        lines.append(f"  OCR: 系统={bool(cfg['ocr']['system']['enabled'])}({platform.system()}) Tesseract={bool(cfg['ocr']['tesseract']['enabled'])}")
        lines.append(f"  MinerU: {'on' if bool(cfg['document']['mineru']['enabled']) else 'off'}")
        return "\n".join(lines)
    raise ValueError(f"未知工具: {name}")


def handle_message(msg: dict) -> dict | None:
    if not isinstance(msg, dict):
        return error(None, -32600, "Invalid Request")
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        return result(mid, {"protocolVersion": PROTOCOL_VERSION,
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                            "instructions": "需要看图时调用 understand_image / vision_analyze；普通文本聊天不要调用。"})
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return result(mid, {})
    if method == "tools/list":
        return result(mid, {"tools": TOOLS})
    if method == "tools/call":
        try:
            text = _run_tool(params.get("name"), params.get("arguments") or {})
            return tool_text(mid, text)
        except Exception as e:
            return tool_text(mid, f"调用失败: {error_text(e)}\n{traceback.format_exc(limit=3)}", is_error=True)
    if "id" not in msg:
        return None
    return error(mid, -32601, f"Method not found: {method}")


def main_loop() -> None:
    print(f"[{SERVER_NAME}] 启动，可调用 vision_status 查看状态", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle_message(msg)
        except Exception as e:
            resp = error(msg.get("id"), -32603, f"Internal error: {error_text(e)}")
        if resp:
            send(resp)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="vision-mcp")
    parser.add_argument("cmd", nargs="?", default=None, help="init = 生成配置 / install = 一键安装配置")
    parser.add_argument("--config", help="覆盖 config.json 路径")
    parser.add_argument("--status", action="store_true", help="打印路由/通道状态")
    parser.add_argument("--verify", metavar="IMAGE", help="对一张图跑一次完整竞速")
    parser.add_argument("--ocr", metavar="IMAGE", help="对一张图跑系统原生 OCR（自动识别平台，不调视觉模型）")
    parser.add_argument("--accurate-ocr", action="store_true", help="OCR 用精确模式")
    parser.add_argument("--prompt", default="Describe this image accurately and briefly.")
    parser.add_argument("--no-cache", action="store_true")
    # 零配置内联模式：给这些参数即可不读 config.json
    parser.add_argument("--api-key", help="极简模式：单通道 API Key")
    parser.add_argument("--base-url", help="极简模式：OpenAI 兼容 chat/completions 地址")
    parser.add_argument("--model", help="极简模式：模型名")
    parser.add_argument("--provider", default="custom", help="极简模式：服务商标识")
    parser.add_argument("--timeout", type=int, default=120, help="极简模式：超时秒数")
    parser.add_argument("--max-tokens", type=int, default=2048, help="极简模式：输出上限")
    args = parser.parse_args()

    # 零配置内联模式：一行命令直接跑，不需要配置文件
    if args.api_key and args.base_url and args.model:
        mem = {
            "default_prompt": DEFAULT_PROMPT,
            "channels": [{
                "id": "custom", "provider": args.provider, "base_url": args.base_url,
                "model": args.model, "api_key": args.api_key, "api_key_env": "",
                "timeout_ms": args.timeout * 1000, "max_tokens": args.max_tokens,
            }],
            "race": ["custom"], "fallback": [],
            "max_tokens": args.max_tokens, "timeout_ms": args.timeout * 1000,
            "max_file_bytes": 15 * 1024 * 1024,
            "cache": {"enabled": False, "directory": "", "ttl_seconds": 0},
            "ocr": {"system": {"enabled": True, "languages": ""}, "tesseract": {"enabled": False}},
            "document": {"mineru": {"enabled": False}},
        }
        _HOLDER["config"] = _MemoryConfig(mem)

    if args.cmd == "install":
        return cmd_install()
    if args.cmd == "init":
        path = init_config()
        print(f"已生成配置: {path}\n请编辑该文件填写 API Key。")
        return 0
    if args.config:
        _HOLDER["config"] = Config(args.config)
    if args.status:
        print(_run_tool("vision_status", {}))
        return 0
    if args.verify:
        env = _router().analyze_file(args.verify, args.prompt, "reason", False, False, args.no_cache)
        print(f"Winner: {env['tool_used']}\nConfidence: {env['confidence']}\n{env['result']}")
        return 0
    if args.ocr:
        path = os.path.expanduser(args.ocr)
        if not os.path.isfile(path):
            print(f"找不到图片: {path}", file=sys.stderr)
            return 1
        raw = open(path, "rb").read()
        mime = mimetypes.guess_type(path)[0] or "image/png"
        env = system_ocr(_router().config, raw, mime, args.accurate_ocr)
        print(f"OCR: {env['tool_used']}\nConfidence: {env['confidence']}\n{env['content']}")
        return 0
    main_loop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
