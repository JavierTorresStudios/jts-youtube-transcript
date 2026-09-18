@echo off
REM jts-youtube-transcript -- double-click launcher (Windows).
REM Installs uv on first run if needed, then runs the tool via "uv run",
REM which handles the Python environment and dependencies automatically.

cd /d "%~dp0.."

where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo First run: installing uv ^(a fast Python package/dependency manager^)...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo JTS YouTube Transcript
echo -----------------------
set /p URL="YouTube URL: "

if "%URL%"=="" (
    echo No URL entered.
    pause
    exit /b 1
)

set COOKIE_ARGS=
set /p MEMBERS="Members-only video, or does it need your YouTube login? (y/N): "
if /i "%MEMBERS%"=="y" (
    set /p BROWSER="Which browser are you logged into YouTube with? (chrome/edge/firefox) [chrome]: "
    if "%BROWSER%"=="" set BROWSER=chrome
    set COOKIE_ARGS=--cookies-from-browser %BROWSER%
)

uv run jts-youtube-transcript "%URL%" %COOKIE_ARGS%

echo.
if %errorlevel%==0 (
    echo Done -- see "Masterclass Transcripts\" for the file.
) else (
    echo Something went wrong ^(exit code %errorlevel%^) -- see the messages above.
)

pause
