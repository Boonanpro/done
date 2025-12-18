@echo off
echo Running tests...
python -m pytest tests/test_api.py -v
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tests failed!
    exit /b 1
)
echo.
echo All tests passed!
