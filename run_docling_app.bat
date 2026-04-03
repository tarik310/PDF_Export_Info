@echo off
REM PDF Export API Başlatıcı
REM Bu dosyanın bulunduğu dizine geçer ve venv içindeki Python ile app.py'yi çalıştırır.
cd /d "%~dp0"
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe app.py
) else (
    echo [ERROR] Virtual environment bulunamadi: venv\Scripts\python.exe
    echo Olusturmak icin: python -m venv venv
    echo Bagimliklar icin: venv\Scripts\pip.exe install -r requirements.txt
    pause
)
