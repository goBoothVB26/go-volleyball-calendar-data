@echo off
REM Publish events.json to GitHub so the website calendar can fetch it.
REM
REM One-time setup (see README section below):
REM   1. Create a PUBLIC repo on github.com, e.g. "volleyball-calendar-data"
REM   2. Install Git for Windows (git-scm.com) if you don't have it
REM   3. Clone it next to this script:
REM        git clone https://github.com/YOUR_USERNAME/volleyball-calendar-data
REM   4. Set the two paths below.

set CALENDAR_DIR=G:\My Drive\Calendar
set REPO_DIR=%~dp0volleyball-calendar-data

copy /Y "%CALENDAR_DIR%\events.json" "%REPO_DIR%\events.json"
cd /d "%REPO_DIR%"
git add events.json
git commit -m "Update events.json"
git push
cd /d "%~dp0"

echo.
echo Published. The website reads:
echo https://raw.githubusercontent.com/YOUR_USERNAME/volleyball-calendar-data/main/events.json
pause
