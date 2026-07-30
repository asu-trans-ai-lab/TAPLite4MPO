@echo off
setlocal

cd /d "%~dp0"

set "SETUP_DIR=setup"
set "ENV_NAME=dtalite_pipeline"
set "LOG_DIR=logs"
set "WHEEL_DIR=%~dp0..\wheels"
set "CONFIG_FILE=%~1"
set "CONFIG_ARG="

if "%CONFIG_FILE%"=="" (
    if exist "configs\project_assignment.json" (
        set "CONFIG_FILE=configs\project_assignment.json"
        set "CONFIG_ARG=configs\project_assignment.json"
    ) else (
        set "CONFIG_FILE=(none; default config not found)"
    )
) else (
    set "CONFIG_ARG=%CONFIG_FILE%"
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "LOG_FILE=%LOG_DIR%\setup_environment_log.txt"

echo ========================================== > "%LOG_FILE%"
echo DTALite Environment Setup Log >> "%LOG_FILE%"
echo Started at: %date% %time% >> "%LOG_FILE%"
echo Project folder: %cd% >> "%LOG_FILE%"
echo Selected config: %CONFIG_FILE% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo ==========================================
echo DTALite Environment Setup
echo Selected config: %CONFIG_FILE%
echo Log file: %LOG_FILE%
echo ==========================================

call "%SETUP_DIR%\install_miniconda_if_needed.bat" >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Conda installation/check failed.
    echo [ERROR] Conda installation/check failed. >> "%LOG_FILE%"
    pause
    exit /b 1
)

set "CONDA_DIR="

if exist "%USERPROFILE%\Miniconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%USERPROFILE%\Miniconda3"
) else if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%USERPROFILE%\anaconda3"
) else if exist "%LOCALAPPDATA%\Miniconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%LOCALAPPDATA%\Miniconda3"
) else if exist "%LOCALAPPDATA%\anaconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%LOCALAPPDATA%\anaconda3"
)

if defined CONDA_DIR (
    call "%CONDA_DIR%\Scripts\activate.bat" >> "%LOG_FILE%" 2>&1
) else (
    call conda activate >> "%LOG_FILE%" 2>&1
)

if %errorlevel% neq 0 (
    echo [ERROR] Conda was not found after setup.
    echo [ERROR] Conda was not found after setup. >> "%LOG_FILE%"
    pause
    exit /b 1
)

conda env list | findstr /C:"%ENV_NAME%" >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Creating Conda environment from %SETUP_DIR%\environment.yml...
    echo [INFO] Creating Conda environment from %SETUP_DIR%\environment.yml... >> "%LOG_FILE%"
    conda env create -f "%SETUP_DIR%\environment.yml" >> "%LOG_FILE%" 2>&1
) else (
    echo [INFO] Updating Conda environment from %SETUP_DIR%\environment.yml...
    echo [INFO] Updating Conda environment from %SETUP_DIR%\environment.yml... >> "%LOG_FILE%"
    conda env update -n "%ENV_NAME%" -f "%SETUP_DIR%\environment.yml" --prune >> "%LOG_FILE%" 2>&1
)

if %errorlevel% neq 0 (
    echo [ERROR] Environment setup failed.
    echo [ERROR] Environment setup failed. >> "%LOG_FILE%"
    pause
    exit /b 1
)

call conda activate "%ENV_NAME%" >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Could not activate Conda environment: %ENV_NAME%
    echo [ERROR] Could not activate Conda environment: %ENV_NAME% >> "%LOG_FILE%"
    pause
    exit /b 1
)

set "TAPLITE_WHEEL="
set "WHEEL_COUNT=0"
for /f "delims=" %%F in ('dir /b /a-d "%WHEEL_DIR%\taplite4mpo-*.whl" 2^>nul') do (
    set /a WHEEL_COUNT+=1 >nul
    set "TAPLITE_WHEEL=%WHEEL_DIR%\%%F"
)

if not "%WHEEL_COUNT%"=="1" (
    echo [ERROR] Expected exactly one taplite4mpo wheel under %WHEEL_DIR%; found %WHEEL_COUNT%.
    echo [ERROR] Expected exactly one taplite4mpo wheel under %WHEEL_DIR%; found %WHEEL_COUNT%. >> "%LOG_FILE%"
    pause
    exit /b 1
)

echo [INFO] Installing bundled TAPLite engine wheel...
echo [INFO] Installing bundled TAPLite engine wheel: %TAPLITE_WHEEL% >> "%LOG_FILE%"
python -m pip install --no-index --no-deps --force-reinstall "%TAPLITE_WHEEL%" >> "%LOG_FILE%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Could not install the bundled TAPLite engine wheel.
    echo [ERROR] Could not install the bundled TAPLite engine wheel. >> "%LOG_FILE%"
    pause
    exit /b 1
)

echo [INFO] Running setup check...
echo [INFO] Running setup check with %CONFIG_FILE%... >> "%LOG_FILE%"
if "%CONFIG_ARG%"=="" (
    python "%SETUP_DIR%\check_setup.py" >> "%LOG_FILE%" 2>&1
) else (
    python "%SETUP_DIR%\check_setup.py" "%CONFIG_ARG%" >> "%LOG_FILE%" 2>&1
)

if %errorlevel% neq 0 (
    echo [ERROR] Setup check failed. Please review %LOG_FILE%.
    pause
    exit /b 1
)

echo [OK] Environment setup and setup check completed successfully.
echo [OK] Environment setup and setup check completed successfully. >> "%LOG_FILE%"
pause
