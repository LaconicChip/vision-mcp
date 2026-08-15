<h1 align="center">vision-mcp</h1>

<p align="center"><strong>Paste an image. Let vision models race. Keep your text-only agent reasoning.</strong></p>

<p align="center">🌐 <a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#routing">Routing</a> ·
  <a href="#register-with-your-agent">Register</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#based-on">Based on</a> ·
  <a href="#license">License</a>
</p>

<p align="center">
  <img alt="version 1.1.0" src="https://img.shields.io/badge/version-1.1.0-0ea5e9?style=flat">
  <img alt="MCP server" src="https://img.shields.io/badge/MCP-stdio-111827?style=flat">
  <img alt="no Python needed" src="https://img.shields.io/badge/install-no%20Python-16a34a?style=flat">
  <img alt="models" src="https://img.shields.io/badge/race-5%20models-4d6bfe?style=flat">
  <img alt="platforms" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-4d6bfe?style=flat">
</p>

<p align="center"><code>agent sees image → understand_image → race ×5 → fallback → grounded text</code></p>

An **agent-agnostic MCP server** (stdio) that gives text-only models a natural image experience. When the connected agent faces a screenshot, upload, UI snapshot, chart, or scan, it calls `understand_image` / `vision_analyze`. The server races multiple vision providers, returns **grounded text**, and the text-only model keeps reasoning normally.

> [!NOTE]
> This project is a standalone, cleaner re-implementation inspired by
> [`Sorwcyra/ds-vision-plugin`](https://github.com/Sorwcyra/ds-vision-plugin).
> It keeps the same routing philosophy but is **agent-agnostic**, **zero-dependency**, and uses a
> **human-friendly JSONC config** instead of a DeepSeek Harness bundle.

## Why it exists

| Problem | This project's answer |
|---|---|
| Paste screenshots directly into a text-only chat | A standard MCP tool (`understand_image`) any agent can call |
| Don't want to wait on one slow or flaky provider | 5 models start together; first valid result wins |
| Keep a proven multi-provider route design | glm ×3 + agnes ×2 race, user-defined fallback |
| Add a private relay, paid model, or local runtime | Add/reorder any OpenAI-compatible channel |
| Configure without hand-editing confusing YAML | JSONC config with inline comments, hot reload |
| Failures should be understandable | Visible error with full attempt log; images never silently dropped |

## Why choose this MCP

- **Agent-agnostic**: standard MCP stdio — works with Codex, Claude Desktop, Cursor, and any MCP client.
- **No Python required**: installs as a single self-contained binary for macOS / Linux / Windows — nothing to set up.
- **Five-model first-success race**: `glm-4v-flash`, `glm-4.1v-thinking-flash`, `glm-4.6v-flash` (⚠️ unstable), `agnes-2.5-flash`, `agnes-2.0-flash`.
- **Free race, paid last-resort**: the five racers are free-tier models. Your own model (`custom-1`) — paid, private, or local — runs only when all five fail or time out, so you don't pay for normal requests.
- **Open-ended routing**: add unlimited OpenAI-compatible channels to the race or the ordered fallback.
- **Explicit failure behavior**: images are never silently discarded; the error includes every attempt.
- **Human-friendly config**: JSONC supports `//` and `#` comments, hot-reloads on save.
- **Caching**: results cached by image content hash (default 7 days) to cut cost and latency.

The five-way race starts five provider requests per uncached image. If request count, cost, or data exposure matters more, remove channels from `routing.race` or prefer local OCR/VLM.

## Routing

```mermaid
flowchart LR
    A["Agent sees an image"] --> B["understand_image / vision_analyze"]
    B --> R["Five-model race<br/>glm-4v + glm-thinking + glm-4.6v<br/>agnes-2.5 + agnes-2.0"]
    B --> O["OCR route<br/>system OCR (macOS / Windows) / Tesseract"]
    B --> C["Custom routes<br/>cloud / relay / local"]
    R --> T["Grounded text block"]
    O --> T
    C --> T
    R -- "all fail / timeout" --> V["Fallback: custom-1 (your own VLM)"]
    V --> T
    T --> D["Text-only agent<br/>continues reasoning"]
```

- Default route filter is not applied — the server answers any client that asks.
- Missing-key channels are skipped immediately and quietly.
- OCR intent uses system-native OCR — Apple Vision on macOS, Windows OCR on Windows, Tesseract on Linux — all local and offline.
- `glm-4.6v-flash` is kept in the race but flagged unstable (rate limits / slow).

## Quick start

### One command, nothing to install (recommended)

No Python. No environment setup. No platform-specific steps. Run one line — it detects your OS, downloads a single self-contained binary, installs it, registers with your agent, and walks you through API keys:

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
iex (irm https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.ps1)
```

What happens under the hood:

1. Detect your OS / CPU → macOS (arm64 + x86_64), Linux (x86_64), Windows (x86_64).
2. Download the matching **single-file binary** from GitHub Releases — **no Python**.
3. Install to `~/.local/bin/vision-mcp` (Windows: `%LOCALAPPDATA%\vision-mcp\vision-mcp.exe`).
4. Auto-register with Codex / Claude Desktop / Cursor when it finds them.
5. Enter your API keys when prompted, restart your agent, and paste an image.

Config is generated at `~/.config/vision-mcp/config.json` (edit anytime — hot-reloads). If no prebuilt binary exists for your platform, the installer falls back to `git clone` + Python.

### Prefer your agent? Let it install itself

Already inside Codex, Claude, or Cursor? Paste the repo link right into your session — the agent installs vision-mcp **into the very agent you're using**:

> `install https://github.com/LaconicChip/vision-mcp`

That's it — no terminal, no commands to copy. Any wording works ("帮我把这个 MCP 装进当前环境" works too). The agent clones the repo, runs the installer, and registers itself.

### Zero-config single channel (advanced)

Point the server at any OpenAI-compatible vision endpoint in one line — **no config file at all**:

```bash
vision-mcp --api-key KEY --base-url https://host/v1/chat/completions --model YOUR_VLM
```

### Other install paths (optional)

<details>
<summary>pip / uvx / from source (requires Python)</summary>

- **pip**: `pip install git+https://github.com/LaconicChip/vision-mcp.git && vision-mcp init`
- **uvx**: `uvx --from git+https://github.com/LaconicChip/vision-mcp vision-mcp --api-key KEY --base-url URL --model MODEL`
- **from source**: `git clone https://github.com/LaconicChip/vision-mcp && cd vision-mcp && python3 server.py`

</details>

## Register with your agent

The one-command installer auto-registers with Codex, Claude Desktop, and Cursor when it finds them. To register manually, point any MCP client at the installed binary (no Python):

### Codex

```toml
# ~/.codex/config.toml
[mcp_servers.vision-mcp]
type = "stdio"
command = "/absolute/path/to/vision-mcp"   # e.g. ~/.local/bin/vision-mcp
args = []
startup_timeout_sec = 120
```

### Claude Desktop / Cursor

```json
// claude_desktop_config.json  /  ~/.cursor/mcp.json
{
  "mcpServers": {
    "vision-mcp": {
      "command": "/absolute/path/to/vision-mcp",
      "args": []
    }
  }
}
```

### Any stdio MCP client

```text
command: /absolute/path/to/vision-mcp
args: []
```

> From a source checkout, use `command: python3` with `args: ["/absolute/path/to/vision-mcp/server.py"]` instead.

## Configuration

`config.json` is **JSONC**: comments with `//` or `#` are allowed, and the server hot-reloads on save. See `config.example.json` for the fully commented template.

Each channel is an OpenAI-compatible `chat/completions` endpoint:

```jsonc
{
  "id": "glm",
  "provider": "zhipu",
  "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
  "model": "glm-4v-flash",
  "api_key": "your-key",          // literal key (priority)
  "api_key_env": "GLM_API_KEY",   // or read from env var
  "timeout_ms": 90000,
  "max_tokens": 2048
}
```

### Built-in channels

| Channel | Model | Key |
|---|---|
| `glm` | glm-4v-flash | `GLM_API_KEY` |
| `glm-thinking` | glm-4.1v-thinking-flash | `GLM_API_KEY` |
| `glm-4.6v-flash` | glm-4.6v-flash (⚠️ unstable) | `GLM_API_KEY` |
| `agnes-2.5-flash` | agnes-2.5-flash | `AGNES_API_KEY` |
| `agnes-2.0-flash` | agnes-2.0-flash | `AGNES_API_KEY` |

> 🎯 **Design philosophy**: the race pool uses **free** models, so racing all five costs nothing. `custom-1` is deliberately left blank — it's the slot for **your own** model (paid, private, or a local relay). It only runs after all five free racers fail or time out, so your paid/private model is never billed on a normal request. Fill in its `base_url`, `model` and key in `config.json` (or set `VISION_CUSTOM_API_KEY`).

Add any OpenAI-compatible vision model by adding a channel and putting its id in `routing.race` or `routing.fallback`.

## Tools

| Tool | Returns | Description |
|---|---|---|
| `understand_image(image, prompt?, intent?, complex?, accurate_ocr?, no_cache?, max_tokens?)` | text | One-call image understanding. |
| `vision_analyze(...)` | JSON | Same, plus `tool_used`, `confidence`, `metadata`, race attempts. |
| `vision_config()` | text | Current models / endpoints / masked keys. |
| `vision_status()` | text | Routing, channel readiness, cache, OCR. |

`image` accepts local absolute path, `http(s)://` URL, `data:` URI, or raw base64.
`intent`: `auto` (default) / `reason` / `ocr` / `document`.

## CLI

When installed as a package, use the `vision-mcp` command; from a checkout, use `python3 server.py`:

```bash
vision-mcp --status                 # routing / channel readiness
vision-mcp --verify /path/x.png     # run one real race, print winner
vision-mcp                          # run as MCP stdio server
```

## Privacy & failure behavior

- Image bytes are sent to configured cloud channels; use local OCR/VLM or disable channels for sensitive data.
- OCR is fully local — Apple Vision (macOS), Windows OCR (Windows), Tesseract (Linux) — image bytes never leave the machine for OCR.
- Keys are masked in `vision_status` / `vision_config` and never included in status output.
- A channel without a key is skipped; requests never silently drop images.
- On total failure, the tool returns a clear error with every attempt recorded.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Covers JSONC/legacy/new config parsing, image input parsing, caching, and missing-key skipping.

## Based on

This project adapts the **multi-provider race + fallback** routing from
[`Sorwcyra/ds-vision-plugin`](https://github.com/Sorwcyra/ds-vision-plugin)
(which itself follows the `ds-vision-skill` four-model pattern). Differences:

- **Agent-agnostic MCP** instead of a DeepSeek Harness bundle.
- **Zero third-party dependencies** — pure Python stdlib.
- **JSONC config** with inline comments and hot reload instead of YAML.
- **Five-model race** (adds `glm-4.6v-flash`) with a **user-defined fallback channel** (`custom-1`).
- **Generic install** for Codex / Claude Desktop / Cursor / any MCP client.

## License

Released under the [MIT License](LICENSE).
