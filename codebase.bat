@echo off
REM Save as UTF-8 without BOM.
setlocal EnableDelayedExpansion

REM ========================================
REM FormsADDA - CODEBASE STATE CHECK
REM ========================================

set "APP_DIR=%~dp0"
set "ERROR_COUNT=0"
set "WARNING_COUNT=0"

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
call :color_echo "%CYAN%" "       FormsADDA STATE CHECK"
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

REM --- Step 0: Source Inventory ---
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

REM --- Step 1: Pip Dependencies ---
call :color_echo "%CYAN%" "[1/4] Dependencies (pip)..."
echo ----------------------------------------
call :color_echo "%YELLOW%" "  Running: pip install -r requirements.txt"
call "%PY%" -m pip install -r requirements.txt
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

REM --- Step 2: Code Quality tools ---
call :color_echo "%CYAN%" "[2/4] Ensuring format/lint tools (black/ruff)..."
echo ----------------------------------------
call "%PY%" -m pip install black ruff >nul 2>&1
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  call :color_echo "%YELLOW%" "  ! Warning: Unable to install black/ruff checking tools"
)

REM Formatting check
call :color_echo "%YELLOW%" "  Running: black check..."
call "%PY%" -m black --check app/ scripts/ >nul 2>&1
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION2_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! black check failed - Run 'black app/ scripts/' to auto-format"
) else (
  set "SECTION2_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK black formatting check passed"
)

REM Lint check
call :color_echo "%YELLOW%" "  Running: ruff check..."
call "%PY%" -m ruff check app/ scripts/ >nul 2>&1
if errorlevel 1 (
  set /a WARNING_COUNT+=1
  set "SECTION3_STATUS=WARNING"
  call :color_echo "%YELLOW%" "  ! ruff check found warnings/errors"
) else (
  set "SECTION3_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK ruff check passed"
)
echo.

REM --- Step 3: Import Integrity ---
call :color_echo "%CYAN%" "[3/4] Application Import integrity..."
echo ----------------------------------------
call "%PY%" -c "from app import create_app; create_app()" >nul 2>&1
if errorlevel 1 (
  set /a ERROR_COUNT+=1
  set "SECTION4_STATUS=FAILED"
  call :color_echo "%RED%" "  X Failed to import or initialize application app context"
) else (
  set "SECTION4_STATUS=PASSED"
  call :color_echo "%GREEN%" "  OK App imports successfully"
)
echo.

:summary
echo.
call :color_echo "%CYAN%" "========================================"
call :color_echo "%CYAN%" "  SUMMARY"
call :color_echo "%CYAN%" "========================================"
echo.
echo   [0] Source inventory:              %SECTION0_STATUS%
echo   [1] Pip dependencies:              %SECTION1_STATUS%
echo   [2] Black formatting:              %SECTION2_STATUS%
echo   [3] Ruff linting:                  %SECTION3_STATUS%
echo   [4] Import integrity:              %SECTION4_STATUS%
echo.

if %ERROR_COUNT% EQU 0 (
    call :color_echo "%GREEN%" "  OK All blocking checks passed!"
    if %WARNING_COUNT% GTR 0 call :color_echo "%YELLOW%" "  Found %WARNING_COUNT% warning(s)"
    echo.
    call :color_echo "%CYAN%" "  Start local development server? (Y/N)"
    choice /C YN /N /M ""
    if errorlevel 2 goto :end
    if errorlevel 1 goto :run_server
) else (
    call :color_echo "%RED%" "  X Found %ERROR_COUNT% error(s)"
    if %WARNING_COUNT% GTR 0 call :color_echo "%YELLOW%" "  Found %WARNING_COUNT% warning(s)"
    echo.
    call :color_echo "%YELLOW%" "  Please fix the errors before running the application."
)
goto :end

:run_server
echo.
call :color_echo "%CYAN%" "[4/4] Starting FormsADDA server..."
call "%PY%" run.py

:end
echo.
call :color_echo "%CYAN%" "========================================"
call :color_echo "%CYAN%" "  CHECK COMPLETE"
call :color_echo "%CYAN%" "========================================"
echo.
if %ERROR_COUNT% GTR 0 (exit /b 1) else (exit /b 0)
