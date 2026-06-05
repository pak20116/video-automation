@echo off
chcp 65001 > nul
echo Starting Video Automation UI...
cd /d "%~dp0"
streamlit run app.py --server.port=8501 --server.headless=false
pause
