@echo off
REM Build a single-file executable (no Python needed by end users).
cd /d "%~dp0.."
python -m pip install --upgrade pyinstaller
python -m PyInstaller --onefile --name vision-mcp server.py
echo.
echo ✅ 构建完成：dist\vision-mcp.exe
echo    注册 MCP 时把 args 指向这个 exe，用户无需安装 Python。
