@echo off
rem Launcher: "ochat [name] [--new | --resume] [--model NAME] [--workspace FOLDER]" from any folder.
rem Uses "python" if it's on PATH, otherwise the "py" launcher from python.org installs.
where python >nul 2>nul
if %errorlevel%==0 (python "%~dp0chat.py" %*) else (py -3 "%~dp0chat.py" %*)
