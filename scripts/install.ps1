# vision-mcp 一键安装（Windows PowerShell，自动判断系统）
# 用法: iex (irm https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.ps1)
$repo = "LaconicChip/vision-mcp"
$tmp = Join-Path $env:TEMP ("vision-mcp-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

# 1) 优先下载预编译二进制（无需 Python）
$asset = "vision-mcp-Windows-x86_64.exe"
$url = "https://github.com/$repo/releases/latest/download/$asset"
$bin = Join-Path $tmp "vision-mcp.exe"
try {
  Invoke-WebRequest -Uri $url -OutFile $bin -UseBasicParsing -ErrorAction Stop
  & $bin install
  Remove-Item -Recurse -Force $tmp
  exit $LASTEXITCODE
} catch {
  Write-Host "（未找到预编译包，回退到 Python 方式...）"
}

# 2) 回退：git + python
git clone --depth 1 "https://github.com/$repo.git" "$tmp\vision-mcp" | Out-Null
Push-Location "$tmp\vision-mcp"
python server.py install
$code = $LASTEXITCODE
Pop-Location
Remove-Item -Recurse -Force $tmp
exit $code
