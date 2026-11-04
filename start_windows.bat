@echo off
chcp 65001 >nul
rem 供應商漲價與報價毛利工具：Windows 啟動（雙擊執行）
rem 只使用本資料夾的 .venv，不需要修改 PowerShell 執行原則或系統設定。
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 尚未安裝。請先在本資料夾執行：
  echo   py -3.11 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements-lock.txt
  echo 詳見 docs\LOCAL_DEPLOYMENT.md 第 2 節。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\check_env.py
if errorlevel 1 (
  pause
  exit /b 1
)
echo 啟動中。請用瀏覽器開啟下方顯示的 Local URL（通常是 http://localhost:8501）。
echo 要關閉程式：在這個視窗按 Ctrl+C，或直接關閉視窗。
".venv\Scripts\python.exe" -m streamlit run app.py
pause
