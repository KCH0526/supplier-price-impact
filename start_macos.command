#!/bin/bash
# 供應商漲價與報價毛利工具：macOS 啟動（在 Finder 中雙擊；第一次可能需按右鍵 > 打開）
# 只使用本資料夾的 .venv，不修改系統設定。
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
  echo "尚未安裝。請先在本資料夾執行："
  echo "  python3.11 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements-lock.txt"
  echo "詳見 docs/LOCAL_DEPLOYMENT.md 第 3 節。"
  read -r -p "按 Enter 關閉…" _
  exit 1
fi
if ! ".venv/bin/python" tools/check_env.py; then
  read -r -p "按 Enter 關閉…" _
  exit 1
fi
echo "啟動中。請用瀏覽器開啟下方顯示的 Local URL（通常是 http://localhost:8501）。"
echo "要關閉程式：在這個視窗按 Control+C。"
".venv/bin/python" -m streamlit run app.py
