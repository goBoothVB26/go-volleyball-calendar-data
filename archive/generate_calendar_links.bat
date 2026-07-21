@echo off
setlocal

set CALENDAR_DIR=G:\My Drive\Calendar

echo === Step 1: Scraping schedules into %CALENDAR_DIR% ===
python -m scraper.main --output-dir "%CALENDAR_DIR%"
if errorlevel 1 goto :error

echo.
echo === Step 2: Generating links.csv template ===
python drive_links.py --init "%CALENDAR_DIR%" -o links.csv
if errorlevel 1 goto :error

echo.
echo links.csv has been created/updated with one row per schedule file.
echo Open links.csv now, paste a Google Drive share_link into each row
echo (leave any existing share_link values you already filled in as-is),
echo save the file, then come back here and press a key to continue.
pause

echo.
echo === Step 3: Converting share links into direct-download URLs ===
python drive_links.py links.csv -o final.csv
if errorlevel 1 goto :error

echo.
echo Done! final.csv contains filename,share_link,direct_url.
echo Copy each direct_url into Google Calendar's "From URL" box.
goto :end

:error
echo.
echo Something went wrong -- see the error above.

:end
echo.
pause
