@echo off
REM This file is part of Extractium(TM)
REM run.bat
REM Author(s): Gabriel Mongefranco.
REM Created: 2026-09-08
REM Last Modified: 2026-09-08
REM Summary: One-command build for Windows. Creates a virtual environment
REM beside this script, installs the pinned dependencies, installs
REM Extractium into it, runs the build, and prints what to commit afterwards.
REM Notes: See README file for documentation and full license information.
REM
REM Copyright (c) 2026 The Regents of the University of Michigan
REM
REM This program is free software: you can redistribute it and/or modify
REM it under the terms of the GNU General Public License as published by
REM the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
REM This program is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
REM GNU General Public License for more details.
REM You should have received a copy of the GNU General Public License along
REM with this program. If not, see <https://www.gnu.org/licenses/>.

setlocal

REM ### Settings ###

REM Where this script lives, with no trailing backslash. The virtual
REM environment and the pinned dependency list are found relative to it, so
REM the script works from any working directory.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

REM The settings file to build from. Set CONFIG before running this script
REM to build from another one, or pass --config yourself as an argument.
if not defined CONFIG set "CONFIG=config.yaml"

REM Where the virtual environment goes. Set VENV_DIR to keep several
REM environments side by side.
if not defined VENV_DIR set "VENV_DIR=%HERE%\.venv"

REM The launcher used to create the environment. Extractium needs Python
REM 3.10 or newer.
if not defined PYTHON set "PYTHON=py -3"

REM ### Create the environment ###

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating a virtual environment in %VENV_DIR% ...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Could not create a virtual environment. Install Python 3.10 or newer, or set PYTHON to its path.
        exit /b 1
    )
)
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

REM ### Install pinned dependencies ###

echo Installing pinned dependencies ...
"%VENV_PYTHON%" -m pip install --quiet --upgrade pip
if errorlevel 1 exit /b 1

REM The lock file carries a hash for every package, so pip refuses anything
REM whose contents do not match what was locked.
"%VENV_PYTHON%" -m pip install --quiet --require-hashes -r "%HERE%\requirements-lock.txt"
if errorlevel 1 exit /b 1

REM Installed without dependencies, because the line above already put the
REM exact locked versions in place.
"%VENV_PYTHON%" -m pip install --quiet --no-deps -e "%HERE%"
if errorlevel 1 exit /b 1

REM ### Run the build ###

if "%~1"=="" (
    echo Building from %CONFIG% ...
    "%VENV_PYTHON%" -m extractium.cli build --config "%CONFIG%"
) else (
    "%VENV_PYTHON%" -m extractium.cli build %*
)
if errorlevel 1 exit /b %errorlevel%

REM ### Say what to do next ###

echo.
echo Build finished. The summary above lists every file that was written.
echo.
echo To publish the result:
echo   1. Add those files to git:   git add ^<output folder^>
echo   2. Commit them:              git commit -m "Rebuild the knowledge index"
echo   3. Push:                     git push
echo.
echo Do not commit the .venv folder or the .kb_cache folder. The cache only
echo saves time on the next run; deleting it is always safe.

endlocal
