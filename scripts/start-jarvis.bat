@echo off
rem Starts the Jarvis phone server and restarts it if it ever crashes. Used for autostart.
cd /d "%~dp0.."
if not exist "%USERPROFILE%\.jarvis" mkdir "%USERPROFILE%\.jarvis"
:loop
.venv\Scripts\python.exe -m jarvis serve >> "%USERPROFILE%\.jarvis\server.log" 2>&1
timeout /t 5 /nobreak >nul
goto loop
