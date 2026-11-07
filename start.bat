@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Создан файл .env из шаблона! Заполните BOT_TOKEN, ADMIN_IDS и DATABASE_URL в файле .env и запустите снова.
    pause
    exit /b
)

echo Запуск Telegram-бота...
".venv\Scripts\python.exe" main.py
pause
