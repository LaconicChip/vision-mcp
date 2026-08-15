# vision-mcp 一键安装（Windows PowerShell，自动判断系统，无需 Python）
# 用法: iex (irm https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.ps1)
$repo = "LaconicChip/vision-mcp"
$binDir = Join-Path $env:LOCALAPPDATA "vision-mcp"
$bin = Join-Path $binDir "vision-mcp.exe"
New-Item -ItemType Directory -Path $binDir -Force | Out-Null

# 1) 优先下载预编译二进制（无需 Python）
$asset = "vision-mcp-Windows-x86_64.exe"
$url = "https://github.com/$repo/releases/latest/download/$asset"
try {
  Invoke-WebRequest -Uri $url -OutFile $bin -UseBasicParsing -ErrorAction Stop
  Write-Host "✅ 已安装 $bin（无需 Python）"
  & $bin install
  exit $LASTEXITCODE
} catch {
  Write-Host "（未找到预编译包，回退到 Python 方式...）"
}

# 2) 回退：git + python（需要 Python）
$tmp = Join-Path $env:TEMP ("vision-mcp-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 "https://github.com/$repo.git" "$tmp\vision-mcp" | Out-Null
Push-Location "$tmp\vision-mcp"
python server.py install
$code = $LASTEXITCODE
Pop-Location
Remove-Item -Recurse -Force $tmp
exit $code
