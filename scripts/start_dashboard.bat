@echo off
rem Lanceur manuel du dashboard ATLAS (http://localhost:8501)
cd /d "C:\bot trading\atlas"
".venv\Scripts\python.exe" -m streamlit run atlas\dashboard\app.py --server.headless true --server.port 8501
