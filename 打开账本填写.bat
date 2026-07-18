@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo 正在启动账本填写页（浏览器会自动打开；关掉本窗口即退出）...
C:\venvs\climb310\Scripts\python.exe climb_journal_edit.py
pause
