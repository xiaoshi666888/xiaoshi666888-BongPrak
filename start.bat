@echo off
cd /d "%~dp0"

echo Stopping old bot instances...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -like '*tg-miniapp-order*' } | ForEach-Object { Write-Host ('Stopping PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo Starting BongPrak bot + Flask...
python -u app.py
