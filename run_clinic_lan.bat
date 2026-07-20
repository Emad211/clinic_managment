@echo off
setlocal
cd /d "%~dp0"

echo =====================================================
echo   Clinic LAN launcher
echo   Accounting:       port 8080
echo   Specialist Clinic: port 8090
echo =====================================================
echo.

if not exist "webapp\start.py" (
    echo [ERROR] webapp\start.py not found.
    pause
    exit /b 1
)
if not exist "specialist_clinic\start.py" (
    echo [ERROR] specialist_clinic\start.py not found.
    pause
    exit /b 1
)

rem Accounting uses the system Python or the active environment, matching webapp/run.bat.
start "Clinic Accounting - 8080" /D "%~dp0webapp" cmd /k python start.py

rem Prefer the Specialist app's known-good virtual environment; fall back to system Python.
if exist "specialist_clinic\.venv\Scripts\python.exe" (
    start "Specialist Clinic - 8090" /D "%~dp0specialist_clinic" cmd /k .venv\Scripts\python.exe start.py
) else (
    start "Specialist Clinic - 8090" /D "%~dp0specialist_clinic" cmd /k python start.py
)

echo Both server windows were opened.
echo On the server PC, open:
echo   http://127.0.0.1:8080
echo   http://127.0.0.1:8090
echo.
echo For other computers, log in to Specialist and open:
echo   Manager ^> Settings ^> Local network

echo Keep both command windows open while the clinic is using the systems.
pause
endlocal
