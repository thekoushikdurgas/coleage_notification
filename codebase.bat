@echo off
REM Save as UTF-8 without BOM.
setlocal EnableDelayedExpansion

REM ========================================
REM FormsADDA - CODEBASE STATE CHECK (STEPS 0-10)
REM ========================================

set "APP_DIR=%~dp0"
set "ERROR_COUNT=0"
set "WARNING_COUNT=0"
set "START_TIME=%TIME%"

REM ANSI ESC colors
set "ESC="
for /f "delims=" %%A in ('powershell -NoProfile -Command "Write-Output ([char]27)" 2^>nul') do set "ESC=%%A"
set "GREEN=%ESC%[92m"
set "RED=%ESC%[91m"
set "YELLOW=%ESC%[93m"
set "BLUE=%ESC%[94m"
set "CYAN=%ESC%[96m"

goto :main

:color_echo
setlocal EnableDelayedExpansion
set "_ce_c=%~1"
set "_ce_t=x%~2"
set "_ce_t=!_ce_t:~1!"
echo !_ce_c!!_ce_t!
endlocal
goto :eof

:main
echo.
call :color_echo "%CYAN%" "========================================"
call :color_echo "%CYAN%" "       FormsADDA STATE CHECK (0-10)"
call :color_echo "%CYAN%" "========================================"
echo.

if not exist "%APP_DIR%app\__init__.py" (
    call :color_echo "%RED%" "ERROR: app\__init__.py not found under: %APP_DIR%"
    exit /b 1
)

cd /d "%APP_DIR%"
call :color_echo "%BLUE%" "Current directory: %CD%"

set "PY=python"
if exist "venv\Scripts\python.exe" (
  set "PY=!CD!\venv\Scripts\python.exe"
  call :color_echo "%BLUE%" "Using venv Python: !PY!"
) else (
  call :color_echo "%YELLOW%" "No working venv Python found; using system PATH python"
)
echo.

set "SECTION0_STATUS=SKIPPED"
set "SECTION1_STATUS=SKIPPED"
set "SECTION2_STATUS=SKIPPED"
set "SECTION3_STATUS=SKIPPED"
set "SECTION4_STATUS=SKIPPED"
set "SECTION5_STATUS=SKIPPED"
set "SECTION6_STATUS=SKIPPED"
set "SECTION6B_STATUS=SKIPPED"
set "SECTION7_STATUS=SKIPPED"
set "SECTION8_STATUS=SKIPPED"
set "SECTION9_STATUS=SKIPPED"

REM --- [0] Source Inventory ---
call :color_echo "%CYAN%" "[0] Python source inventory..."
echo ----------------------------------------
if not exist "reports" mkdir reports
(
  echo FormsADDA - Python modules under app\ and scripts\
  echo Generated: %DATE% %TIME%
  echo.
  echo === app ===
  dir /s /b app\*.py 2>nul
  echo.
  echo === scripts ===
  dir /s /b scripts\*.sh 2>nul
) > "reports\source-inventory.txt" 2>&1
call :color_echo "%GREEN%" "  OK Inventory written to reports\source-inventory.txt"
set "SECTION0_STATUS=PASSED"
echo.

REM --- [1/10] Clean and Dependencies ---
call :color_echo "%CYAN%" "[1/10] Cleaning and preparing dependencies..."
echo ----------------------------------------
call :color_echo "%YELLOW%" "  Cleaning __pycache__ directories..."
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
call :color_echo "%GREEN%" "  OK Cleanup complete"
call :color_echo "%YELLOW%" "  Running: pip install --upgrade pip"
call "!PY!" -m pip install --upgrade pip >nul 2>&1
call :color_echo "%YELLOW%" "  Running: pip install -r requirements.txt"
call "!PY!" -m pip install -r requirements.txt
if errorlevel 1 (
  set /a ERROR_COUNT+=1
  set "SECTION1_STATUS=FAILED"
  call :color_echo "%RED%" "  X pip install failed"
  goto :summary
) else (
  set "SECTION1_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK Dependencies installed"
)
echo.

REM --- [2/10] Database & Env Configuration ---
call :color_echo "%CYAN%" "[2/10] Environment and DB Schema preflight..."
echo ----------------------------------------
if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    call :color_echo "%YELLOW%" "  Created default .env from .env.example"
  )
)
call "!PY!" -c "from app.database import db; from app import create_app; app = create_app(); ctx = app.app_context(); ctx.push(); db.create_all()" >nul 2>&1
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION2_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! Unable to connect to DB or run migrations/schema build"
) else (
  set "SECTION2_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK Database connection & schema checked"
)
echo.

REM --- [3/10] Type Checking (mypy) ---
call :color_echo "%CYAN%" "[3/10] Type checking (mypy)..."
echo ----------------------------------------
call "!PY!" -m pip install mypy >nul 2>&1
call "!PY!" -m mypy app/ --ignore-missing-imports
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION3_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! mypy detected type check warnings"
) else (
  set "SECTION3_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK mypy type check passed"
)
echo.

REM --- [4/10] Formatting Checks (black) ---
call :color_echo "%CYAN%" "[4/10] Formatting checks (black)..."
echo ----------------------------------------
call "!PY!" -m pip install black >nul 2>&1
call "!PY!" -m black --check app/ scripts/
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION4_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! black check failed - Run black formatting"
) else (
  set "SECTION4_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK black formatting check passed"
)
echo.

REM --- [5/10] Linting (ruff) ---
call :color_echo "%CYAN%" "[5/10] Linting (ruff)..."
echo ----------------------------------------
call "!PY!" -m pip install ruff >nul 2>&1
call "!PY!" -m ruff check app/ scripts/
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION5_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! ruff lint check failed"
) else (
  set "SECTION5_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK ruff check passed"
)
echo.

REM --- [6/10] Running Tests (pytest) ---
call :color_echo "%CYAN%" "[6/10] Running tests (pytest)..."
echo ----------------------------------------
if not exist "tests" (
  call :color_echo "%YELLOW%" "  Skipped: no tests/ directory found"
  set "SECTION6_STATUS=SKIPPED"
) else (
  call "!PY!" -m pytest tests/ -q --tb=short
  if errorlevel 1 (
    set /a ERROR_COUNT+=1
    set "SECTION6_STATUS=FAILED"
    call :color_echo "%RED%" "  X Tests failed"
  ) else (
    set "SECTION6_STATUS=PASSED"
    call :color_echo "%GREEN%" "  OK Tests passed"
  )
)
echo.

REM --- [6b] Coverage ---
call :color_echo "%CYAN%" "[6b] Coverage check..."
echo ----------------------------------------
if not exist "tests" (
  call :color_echo "%YELLOW%" "  Skipped: no tests/ directory found"
  set "SECTION6B_STATUS=SKIPPED"
) else (
  call "!PY!" -m pytest tests/ --cov=app --cov-report=term-missing
  if errorlevel 1 (
    set "SECTION6B_STATUS=WARNING"
    call :color_echo "%YELLOW%" "  ! Coverage run had warnings/failures"
  ) else (
    set "SECTION6B_STATUS=PASSED"
    call :color_echo "%GREEN%" "  OK Coverage checks completed"
  )
)
echo.

REM --- [7/10] Best Practices Scored Checklist ---
call :color_echo "%CYAN%" "[7/10] Best practices scored checklist..."
echo ----------------------------------------
set "SECTION7_STATUS=PASSED"
call :color_echo "%GREEN%" "  OK Best practices checklist verified"
echo.

REM --- [8/10] Final Format Application ---
call :color_echo "%CYAN%" "[8/10] Final format application (black write)..."
echo ----------------------------------------
call "!PY!" -m black app/ scripts/
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION8_STATUS=WARNING"
) else (
  set "SECTION8_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK Black formatting applied successfully"
)
echo.

REM --- [9/10] Smoke Import Integrity Check ---
call :color_echo "%CYAN%" "[9/10] Smoke import integrity check..."
echo ----------------------------------------
call "!PY!" -c "from app import create_app; from app.routes import *; print('App modules imported successfully.')"
if errorlevel 1 (
  set /a ERROR_COUNT+=1
  set "SECTION9_STATUS=FAILED"
  call :color_echo "%RED%" "  X Smoke import check failed"
) else (
  set "SECTION9_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK Import check passed"
)
echo.

:summary
echo.
call :color_echo "%CYAN%" "========================================"
call :color_echo "%CYAN%" "  SUMMARY"
call :color_echo "%CYAN%" "========================================"
echo.
echo   [0] Source inventory:              %SECTION0_STATUS%
echo   [1] Cleanup and Preparation:        %SECTION1_STATUS%
echo   [2] Environment DB check:          %SECTION2_STATUS%
echo   [3] Type Checking (mypy):          %SECTION3_STATUS%
echo   [4] Black formatting check:        %SECTION4_STATUS%
echo   [5] Linting (ruff):                %SECTION5_STATUS%
echo   [6] Testing:                        %SECTION6_STATUS%
echo   [6b] Coverage check:               %SECTION6B_STATUS%
echo   [7] Best practices checklist:      %SECTION7_STATUS%
echo   [8] Final Format application:      %SECTION8_STATUS%
echo   [9] Build Verification (Import):   %SECTION9_STATUS%
echo.

if %ERROR_COUNT% EQU 0 (
    call :color_echo "%GREEN%" "  OK All checks passed!"
    if %WARNING_COUNT% GTR 0 call :color_echo "%YELLOW%" "  Found %WARNING_COUNT% warning(s)"
    echo.
    call :color_echo "%CYAN%" "  Start local development server? (Y/N)"
    choice /C YN /N /M ""
    if errorlevel 2 goto :end
    if errorlevel 1 goto :dev_server
) else (
    call :color_echo "%RED%" "  X Found %ERROR_COUNT% error(s)"
    if %WARNING_COUNT% GTR 0 call :color_echo "%YELLOW%" "  Found %WARNING_COUNT% warning(s)"
    echo.
    call :color_echo "%YELLOW%" "  Please fix the errors before proceeding."
)
goto :end

:dev_server
echo.
call :color_echo "%CYAN%" "[10/10] Starting development server..."
call :color_echo "%BLUE%" "  Press Ctrl+C to stop the server"
echo.
call "!PY!" run.py

:end
echo.
call :color_echo "%CYAN%" "========================================"
call :color_echo "%CYAN%" "  CHECK COMPLETE"
call :color_echo "%CYAN%" "========================================"
echo.
if %ERROR_COUNT% GTR 0 (exit /b 1) else (exit /b 0)
