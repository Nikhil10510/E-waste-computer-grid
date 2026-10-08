@echo off
REM ===================================================
REM E-Waste Compute Grid — Teammate Benchmark Runner
REM Owner: Nikhil Kumar
REM ===================================================
echo [E-WASTE] Checking Python installation...

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on your PATH.
    echo Please install Python 3.8+ or run from your Python environment.
    pause
    exit /b 1
)

echo [E-WASTE] Ensuring required packages are installed (numpy, psutil)...
python -m pip install numpy psutil --quiet

echo [E-WASTE] Running Hardware Detection and Matrix Benchmark...
python "%~dp0hardware_benchmark.py" --verbose

echo.
echo [E-WASTE] Done! Please share the Score, GFLOPS, and Device Type printed above with Nikhil.
pause
