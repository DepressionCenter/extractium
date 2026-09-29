@echo off
REM This file is part of Extractium(TM)
REM run.bat
REM Author(s): Gabriel Mongefranco.
REM Created: 2026-09-08
REM Last Modified: 2026-09-30
REM Summary: The double-click entry point for Windows. Runs Extractium from
REM the Extractium folder beside this script, as the release zip holds,
REM or from the per-user install, and installs first when there is
REM neither. With no argument it builds, or sets up on a first run;
REM "run.bat ui" opens the local page; any other argument goes to the
REM build command.
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

setlocal EnableExtensions

REM ### Settings ###

REM Where this script lives, with no trailing backslash.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

REM Where the installer is fetched from when nothing is installed yet.
if not defined EXTRACTIUM_REPO set "EXTRACTIUM_REPO=https://github.com/DepressionCenter/extractium"

REM The per-user install, used by its full path so this works before a
REM new terminal has picked PATH up, and when PATH could not be changed.
set "USER_SHIM=%LOCALAPPDATA%\Extractium\bin\extractium.cmd"

REM ### Find Extractium ###

set "SHIM="
if exist "%HERE%\Extractium\bin\extractium.cmd" set "SHIM=%HERE%\Extractium\bin\extractium.cmd"
if not defined SHIM if exist "%USER_SHIM%" set "SHIM=%USER_SHIM%"
if defined SHIM goto :run

REM Nothing is installed yet. The installer beside this script, as in a
REM checkout, is run; otherwise the newest release's installer is
REM fetched and run. Either way the install lands under the profile.
if exist "%HERE%\install.bat" (
    call "%HERE%\install.bat"
) else (
    call :fetch_installer
)
if errorlevel 1 exit /b %errorlevel%
if not exist "%USER_SHIM%" (
    echo The install did not finish, so there is nothing to run yet.
    exit /b 1
)
set "SHIM=%USER_SHIM%"

:run

REM ### Run ###

REM CONFIG names another settings file for the page and for a build with
REM no other argument.
set "CONFIG_ARGS="
if defined CONFIG set CONFIG_ARGS=--config "%CONFIG%"

if /i "%~1"=="ui" (
    "%SHIM%" ui %CONFIG_ARGS% %2 %3 %4 %5 %6 %7 %8 %9
) else if "%~1"=="" (
    "%SHIM%" start %CONFIG_ARGS%
) else (
    "%SHIM%" build %*
)
exit /b %errorlevel%

:fetch_installer
set "STAGING=%TEMP%\extractium-installer-%RANDOM%"
mkdir "%STAGING%"
echo Downloading the Extractium installer ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%EXTRACTIUM_REPO%/releases/latest/download/install.bat' -OutFile '%STAGING%\install.bat'"
if errorlevel 1 (
    echo The installer could not be downloaded. Check the network, or save install.bat from the
    echo releases page beside this script and run this script again.
    rmdir /s /q "%STAGING%"
    exit /b 1
)
call "%STAGING%\install.bat"
set "CODE=%errorlevel%"
rmdir /s /q "%STAGING%"
exit /b %CODE%
