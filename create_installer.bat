@echo off
chcp 65001 >nul

echo ============================
echo Сборка приложения
echo ============================

cd /d "%~dp0"

set PYTHON_EXE=C:\Users\shebordaev.id\AppData\Local\Programs\Python\Python313\python.exe

echo Удаляем старые сборки...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist IFC_Validator.spec del /q IFC_Validator.spec

echo Запускаем сборку...
"%PYTHON_EXE%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "IFC_Validator" ^
    --icon "iconka.ico" ^
    --add-data "ifc_ids_validator;ifc_ids_validator" ^
    --hidden-import ifc_ids_validator.game ^
    --collect-all ifcopenshell ^
    --collect-all ifctester ^
    --collect-all chardet ^
    --collect-all pygame ^
    --collect-all openpyxl ^
    main.py

echo ============================
echo Готово!
echo ============================

pause