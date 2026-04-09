@echo off
chcp 65001 >nul
setlocal

echo ============================
echo Сборка приложения (PyInstaller)
echo ============================

cd /d "%~dp0"

set "VENV_PY=env\Scripts\python.exe"

REM Проверяем наличие Python в виртуальном окружении
if not exist "%VENV_PY%" (
    echo [ОШИБКА] Не найден интерпретатор виртуального окружения:
    echo %VENV_PY%
    pause
    exit /b 1
)

echo Используем Python из виртуального окружения:
"%VENV_PY%" --version

REM Проверяем наличие PyInstaller, если нет — устанавливаем из папки packages
"%VENV_PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller не найден в env. Устанавливаем из папки packages...

    if not exist "packages" (
        echo [ОШИБКА] Не найдена папка packages рядом с bat-файлом.
        pause
        exit /b 1
    )

    "%VENV_PY%" -m pip install --no-index --find-links=packages pyinstaller
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить PyInstaller из папки packages.
        pause
        exit /b 1
    )
)

REM Удаляем старые сборки
echo Удаляем старые сборки...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist IFC_Validator.spec del /q IFC_Validator.spec

REM Сборка
echo Запускаем PyInstaller...
"%VENV_PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "IFC_Validator" ^
    --icon "iconka.ico" ^
    --add-data "ifc_ids_validator;ifc_ids_validator" ^
    "main.py"

if errorlevel 1 (
    echo ============================
    echo Сборка завершилась с ошибкой
    echo ============================
    pause
    exit /b 1
)

echo ============================
echo Сборка успешно завершена!
echo Файл: dist\IFC_Validator.exe
echo ============================

pause