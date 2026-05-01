@echo off
chcp 65001 >nul

echo ============================
echo Сборка приложения
echo ============================

cd /d "%~dp0"

echo Удаляем старые сборки...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist IFC_Validator.spec del /q IFC_Validator.spec

echo Запускаем сборку...
pyinstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "IFC_Validator" ^
    --icon "iconka.ico" ^
    --add-data "ifc_ids_validator;ifc_ids_validator" ^
    --collect-all ifcopenshell ^
    --collect-all ifctester ^
    main.py

echo ============================
echo Готово!
echo ============================

pause