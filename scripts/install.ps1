# vision-mcp 一键安装（Windows PowerShell）
# 用法: iex (irm https://raw.githubusercontent.com/LaconicChip/vision-mcp/main/scripts/install.ps1)
param([string]$Target = "codex")  # codex | claude | cursor | all

$repo = "https://github.com/LaconicChip/vision-mcp.git"
$tmp = Join-Path $env:TEMP ("vision-mcp-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 $repo $tmp | Out-Null
if (-not $?) { Write-Error "git clone 失败"; exit 1 }

Push-Location $tmp
python install.py --for $Target
Pop-Location
Remove-Item -Recurse -Force $tmp

Write-Host ""
Write-Host "✅ 完成。请编辑配置填写 API Key：" -ForegroundColor Green
Write-Host "   $HOME\.mcp-servers\vision-mcp\config.json"
Write-Host "然后重启你的 Agent。"
