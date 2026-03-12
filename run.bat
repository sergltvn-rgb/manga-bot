@echo off
:: Устанавливаем кодировку UTF-8
chcp 65001 >nul

:: Переходим в папку со скриптом
cd /d "%~dp0"

echo ====================================================
echo   ДИАГНОСТИКА ЗАПУСКА (Окно не закроется само)
echo ====================================================
echo.
echo Текущая папка: %cd%
echo.

:loop
:: 1. Проверяем, видит ли система Python
echo [1/2] Проверка Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [!] ОШИБКА: Команда "python" не работает.
    echo Попробуем команду "py"...
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [!!!] КРИТИЧЕСКАЯ ОШИБКА: Python не найден в системе.
        echo 1. Установите Python с сайта python.org
        echo 2. При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH".
        echo.
        pause
        exit
    ) else (
        set py_cmd=py
    )
) else (
    set py_cmd=python
)

:: 2. Проверяем наличие файла бота
echo [2/2] Проверка файла bot.py...
if not exist bot.py (
    echo.
    echo [!] ОШИБКА: Файл bot.py не найден в этой папке.
    echo.
    echo Список файлов в папке сейчас:
    dir /b
    echo.
    echo Убедитесь, что ваш файл называется именно "bot.py" без русских букв.
    echo Если он называется "bot.ру", переименуйте его.
    echo.
    pause
    goto loop
)

echo.
echo === ЗАПУСК БОТА ===
echo Используемая команда: %py_cmd%
echo.

%py_cmd% bot.py

echo.
echo [!] Бот завершил работу или упал. 
echo Нажмите любую кнопку, чтобы попробовать запустить снова через 5 секунд...
pause
timeout /t 5
goto loop