@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title IFC Checker - сборка EXE

rem Положите BAT рядом с main.py, папкой ifc_ids_validator и ifc_checker.ico.
rem При необходимости заранее задайте IFC_PYTHON_EXE полным путем к python.exe.

pushd "%~dp0"
if errorlevel 1 goto :folder_error
set "IFC_BUILD_LOG=%CD%\build_exe.log"
set "IFC_BUILD_PYTHON="
set "MPLBACKEND=Agg"
set "PYTHONIOENCODING=utf-8"

> "%IFC_BUILD_LOG%" echo IFC Checker build started: %DATE% %TIME%
echo ================================================
echo Сборка IFC_Validator.exe
echo ================================================
echo Подробный журнал: "%IFC_BUILD_LOG%"
echo.

if defined IFC_PYTHON_EXE set "IFC_BUILD_PYTHON=%IFC_PYTHON_EXE%"
if defined IFC_BUILD_PYTHON goto :python_ready
if exist ".venv\Scripts\python.exe" set "IFC_BUILD_PYTHON=%CD%\.venv\Scripts\python.exe"
if defined IFC_BUILD_PYTHON goto :python_ready
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "IFC_BUILD_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined IFC_BUILD_PYTHON goto :python_ready
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "IFC_BUILD_PYTHON=%%P"
if defined IFC_BUILD_PYTHON goto :python_ready
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "IFC_BUILD_PYTHON=%%P"
if not defined IFC_BUILD_PYTHON goto :python_missing

:python_ready
if not exist "%IFC_BUILD_PYTHON%" goto :python_missing
echo Python: "%IFC_BUILD_PYTHON%"
"%IFC_BUILD_PYTHON%" -c "import sys,struct; print(sys.version); assert sys.version_info >= (3,10) and struct.calcsize('P') == 8, 'Python 3.10+ x64 is required'" >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 (
    echo ОШИБКА: нужен 64-разрядный Python версии 3.10 или новее.
    goto :failed
)

for %%F in ("main.py" "ifc_checker.ico" "ifc_ids_validator\__init__.py" "ifc_ids_validator\ui_main.py" "ifc_ids_validator\validator.py" "ifc_ids_validator\config.py" "ifc_ids_validator\summary.py" "ifc_ids_validator\report_postprocess.py" "ifc_ids_validator\game.py" "ifc_ids_validator\ifc_preview.py" "ifc_ids_validator\app_icon.py") do (
    if not exist "%%~F" (
        echo ОШИБКА: отсутствует файл "%%~F".
        echo Скачайте актуальные файлы проекта и повторите сборку.
        goto :failed
    )
)

rem В старом main.py без freeze_support параллельные проверки в EXE не работают.
"%IFC_BUILD_PYTHON%" -c "import ast,pathlib; tree=ast.parse(pathlib.Path('main.py').read_text(encoding='utf-8-sig')); assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='freeze_support' for n in ast.walk(tree)), 'Update main.py: multiprocessing.freeze_support() is required'" >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 (
    echo ОШИБКА: обновите main.py до версии с multiprocessing.freeze_support.
    goto :failed
)

echo [1/4] Проверка pip...
"%IFC_BUILD_PYTHON%" -m pip --version >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 (
    "%IFC_BUILD_PYTHON%" -m ensurepip --upgrade >> "%IFC_BUILD_LOG%" 2>&1
    if errorlevel 1 goto :failed
)

echo [2/4] Установка недостающих зависимостей...
"%IFC_BUILD_PYTHON%" -m pip install --disable-pip-version-check ^
    "pyinstaller>=6.11,<7" pyinstaller-hooks-contrib ^
    "ifcopenshell>=0.8,<1" "ifctester>=0.8,<1" ^
    "matplotlib>=3.7,<4" beautifulsoup4 chardet pygame openpyxl ^
    >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [3/4] Проверка исходников, библиотек и схем IDS...
"%IFC_BUILD_PYTHON%" -m compileall -q main.py ifc_ids_validator >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed
"%IFC_BUILD_PYTHON%" -c "import tkinter,ifcopenshell,chardet,bs4,pygame,openpyxl; from ifctester import ids,reporter; ids.get_schema(); from matplotlib.backends.backend_agg import FigureCanvasAgg; from mpl_toolkits.mplot3d.art3d import Poly3DCollection; from ifc_ids_validator.ui_main import App; from ifc_ids_validator.ifc_preview import preview_worker; print('Imports and IDS schema: OK')" >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [4/4] Упаковка EXE. Это может занять несколько минут...
"%IFC_BUILD_PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --noupx ^
    --name "IFC_Validator" ^
    --icon "ifc_checker.ico" ^
    --distpath "dist" ^
    --workpath "build" ^
    --specpath "." ^
    --collect-submodules ifc_ids_validator ^
    --hidden-import multiprocessing.spawn ^
    --hidden-import matplotlib.backends.backend_agg ^
    --hidden-import mpl_toolkits.mplot3d ^
    --collect-data matplotlib ^
    --collect-all ifcopenshell ^
    --collect-all ifctester ^
    --collect-all xmlschema ^
    --collect-all elementpath ^
    --collect-all chardet ^
    --collect-all pygame ^
    --collect-all openpyxl ^
    --exclude-module PyQt5 ^
    --exclude-module PyQt6 ^
    --exclude-module PySide2 ^
    --exclude-module PySide6 ^
    "main.py" >> "%IFC_BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed
if not exist "dist\IFC_Validator.exe" goto :failed

echo.
echo ================================================
echo Готово: "%CD%\dist\IFC_Validator.exe"
echo ================================================
echo Для запуска готового EXE Python не нужен.
pause
popd
endlocal
exit /b 0

:python_missing
echo ОШИБКА: Python не найден.
echo Укажите полный путь к python.exe в переменной IFC_PYTHON_EXE.
goto :failed

:failed
echo.
echo Сборка не завершена. Подробности: "%IFC_BUILD_LOG%"
echo Сообщение об ошибке находится в конце журнала.
pause
popd
endlocal
exit /b 1

:folder_error
echo ОШИБКА: не удалось открыть папку с BAT-файлом.
pause
endlocal
exit /b 1
