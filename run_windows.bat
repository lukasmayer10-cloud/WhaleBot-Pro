@echo off
title WhaleBot Pro X 6.1 POSITION MANAGER
echo Starting WhaleBot Pro X 6.1 POSITION MANAGER...

if not exist .venv (
  python -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Open in browser:
echo http://127.0.0.1:8080
echo.

python main.py
pause
