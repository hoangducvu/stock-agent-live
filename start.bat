@echo off
TITLE StockAgent
cd /d "%~dp0"

echo ============================================
echo   StockAgent Demo - Starting...
echo ============================================
echo.

REM --- Step 1: Backend deps ---
echo [1/3] Installing backend dependencies...
pip install fastapi "uvicorn[standard]" httpx pydantic --quiet 2>nul
if errorlevel 1 pip3 install fastapi "uvicorn[standard]" httpx pydantic --quiet

REM --- Step 2: Frontend deps ---
REM Check for Windows-native vite.cmd (Linux installs won't have this)
echo [2/3] Checking frontend dependencies...
cd frontend
if exist node_modules\.bin\vite.cmd (
    echo     Dependencies OK.
) else (
    echo     Installing for Windows (takes ~60 seconds first time)...
    if exist node_modules rmdir /s /q node_modules 2>nul
    npm install
    if errorlevel 1 (
        echo.
        echo ERROR: npm install failed.
        echo Make sure Node.js is installed: https://nodejs.org
        pause
        exit /b 1
    )
)
cd ..

REM --- Step 3: Start backend ---
echo [3/3] Starting backend (port 8000)...
start "StockAgent Backend" /MIN cmd /c "python -m uvicorn backend.main:app --port 8000 --host 0.0.0.0"
timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo   Browser:  http://localhost:5173
echo   Mobile:   http://%COMPUTERNAME%:5173
echo ============================================
echo.
echo  Press Ctrl+C to stop.
echo.

cd frontend
node_modules\.bin\vite.cmd
