@echo off
REM This file is part of Extractium(TM)
REM run.bat
REM Author(s): Gabriel Mongefranco.
REM Created: 2026-09-08
REM Last Modified: 2026-09-15
REM Summary: One-command build for Windows. Downloads Extractium when this
REM script is on its own, creates a virtual environment beside the checkout,
REM installs the pinned dependencies, installs Extractium into it, writes a
REM first settings file by asking three questions when there is none, runs
REM the build, and prints what to commit afterwards.
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

REM The settings file to build from, relative to the folder you run the
REM script in. Set CONFIG before running this script to build from another
REM one, or pass --config yourself as an argument.
if not defined CONFIG set "CONFIG=config.yaml"

REM Where the virtual environment goes. Set VENV_DIR to keep several
REM environments side by side.
if not defined VENV_DIR set "VENV_DIR=%HERE%\.venv"

REM The interpreter used to create the environment. Extractium needs Python
REM 3.10 or newer. A standard build is preferred: the free-threaded build,
REM the one the launcher lists as 3.13t or 3.14t and picks by default once
REM installed, cannot use the compiled wheels the code parsers ship. PYTHON
REM is checked when it is set; otherwise the launcher is asked for one
REM release after another, and the first standard build is kept. When only a free-threaded build exists, it is
REM used and the parsers are left out of the install.
set "CHOSEN="
set "FREE_THREADED_ONLY="
set "TRY_MODE=standard"
if defined PYTHON call :try_python %PYTHON%
if defined PYTHON if not defined CHOSEN set "REPLACING=1"
if not defined CHOSEN call :choose_python
if not defined CHOSEN (
    echo No Python 3.10 or newer was found. Install one from python.org, or set PYTHON to the
    echo path of one, for example: set PYTHON="C:\Program Files\Python314\python.exe"
    exit /b 1
)
if defined REPLACING if not defined FREE_THREADED_ONLY echo PYTHON names a free-threaded or older build; using %CHOSEN% instead.
set "PYTHON=%CHOSEN%"

REM Where Extractium is downloaded from, and which release, when this
REM script was saved on its own rather than run from inside a checkout.
REM "latest" means the newest published release, looked up when the script
REM runs. A tag or a branch name pins one. The download lands in
REM EXTRACTIUM_DIR.
if not defined EXTRACTIUM_REPO set "EXTRACTIUM_REPO=https://github.com/DepressionCenter/extractium"
if not defined EXTRACTIUM_REF set "EXTRACTIUM_REF=latest"

REM That folder name is deliberately not a valid Python module name. A
REM folder named "extractium" beside the settings file is taken for the
REM package itself by anything that puts the working directory on the
REM import path, and the checkout's outer folder is not the package.
if not defined EXTRACTIUM_DIR set "EXTRACTIUM_DIR=%HERE%\extractium-src"

REM ### Get Extractium if this script is on its own ###

if exist "%HERE%\pyproject.toml" goto :environment
if exist "%EXTRACTIUM_DIR%\pyproject.toml" goto :handover

REM "latest" becomes the newest release's tag. GitHub answers the
REM releases/latest address with a redirect to that release's page, and
REM the tag is the last part of where it lands.
if /i not "%EXTRACTIUM_REF%"=="latest" goto :ref_known
set "LANDED="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $r = [Net.WebRequest]::Create('%EXTRACTIUM_REPO%/releases/latest'); $r.AllowAutoRedirect = $false; $r.GetResponse().Headers['Location']"`) do set "LANDED=%%L"
if not defined LANDED for /f "usebackq delims=" %%L in (`%PYTHON% -c "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1]).geturl())" "%EXTRACTIUM_REPO%/releases/latest"`) do set "LANDED=%%L"
call :tag_from_landed
if not defined EXTRACTIUM_TAG (
    echo No published release was found at %EXTRACTIUM_REPO%/releases/latest. Set EXTRACTIUM_REF to a tag or branch name.
    exit /b 1
)
set "EXTRACTIUM_REF=%EXTRACTIUM_TAG%"
:ref_known

echo Downloading Extractium %EXTRACTIUM_REF% into %EXTRACTIUM_DIR% ...

REM git first, when it is installed.
where git >nul 2>nul
if not errorlevel 1 (
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "%EXTRACTIUM_REF%" "%EXTRACTIUM_REPO%" "%EXTRACTIUM_DIR%"
    if not errorlevel 1 goto :handover
    echo git could not clone the repository; downloading the release archive instead.
)

REM Otherwise the release archive, fetched and unpacked by PowerShell, which
REM every supported Windows carries, with Python's own library as the last
REM resort. Nothing else has to be installed.
set "ARCHIVE=%EXTRACTIUM_REPO%/archive/%EXTRACTIUM_REF%.zip"
set "STAGING=%TEMP%\extractium-download-%RANDOM%"
mkdir "%STAGING%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ARCHIVE%' -OutFile '%STAGING%\extractium.zip'; Expand-Archive -Path '%STAGING%\extractium.zip' -DestinationPath '%STAGING%' -Force"
if errorlevel 1 (
    %PYTHON% -c "import sys, urllib.request, zipfile; urllib.request.urlretrieve(sys.argv[1], sys.argv[2]); zipfile.ZipFile(sys.argv[2]).extractall(sys.argv[3])" "%ARCHIVE%" "%STAGING%\extractium.zip" "%STAGING%"
    if errorlevel 1 (
        echo Extractium could not be downloaded. Check the network, or install git and run this script again.
        exit /b 1
    )
)

REM The archive holds one top-level folder named after the release.
set "UNPACKED="
for /d %%D in ("%STAGING%\*") do if not defined UNPACKED set "UNPACKED=%%D"
if not defined UNPACKED (
    echo The downloaded archive was empty. Check EXTRACTIUM_REF ^(%EXTRACTIUM_REF%^).
    exit /b 1
)
if not exist "%UNPACKED%\pyproject.toml" (
    echo The downloaded archive did not hold Extractium. Check EXTRACTIUM_REF ^(%EXTRACTIUM_REF%^).
    exit /b 1
)
move /y "%UNPACKED%" "%EXTRACTIUM_DIR%" >nul
rmdir /s /q "%STAGING%"
goto :handover

:choose_python
REM Tries the launcher's default, then each release from newest to oldest,
REM then a python on the path. The first pass keeps the first standard
REM build that is 3.10 or newer; the second, reached only when there is
REM none, keeps any 3.10 or newer. A candidate that is missing simply
REM fails the check.
set "TRY_MODE=standard"
for %%C in ("py -3" "py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10" "python") do if not defined CHOSEN call :try_python %%~C
if defined CHOSEN goto :eof
set "TRY_MODE=any"
for %%C in ("py -3" "py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10" "python") do if not defined CHOSEN call :try_python %%~C
if defined CHOSEN set "FREE_THREADED_ONLY=1"
goto :eof

:try_python
REM Keeps the command given as the arguments when it runs a Python that is
REM 3.10 or newer and, in standard mode, not free-threaded.
if "%TRY_MODE%"=="any" goto :try_any
%* -c "import sys, sysconfig; sys.exit(0 if sys.version_info >= (3, 10) and not sysconfig.get_config_var('Py_GIL_DISABLED') else 1)" >nul 2>&1
goto :try_done
:try_any
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
:try_done
if not errorlevel 1 set "CHOSEN=%*"
goto :eof

:renew_free_threaded_venv
REM An environment made earlier with a free-threaded Python cannot install
REM the parsers. It is made again with the standard build found above.
"%VENV_PYTHON%" -c "import sys, sysconfig; sys.exit(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)" >nul 2>&1
if not errorlevel 1 goto :eof
echo The environment in %VENV_DIR% was made with a free-threaded Python. Making it again with %PYTHON% ...
rmdir /s /q "%VENV_DIR%"
goto :eof

:tag_from_landed
REM The tag is what follows /releases/tag/ in the address the redirect
REM named. Anything else means there is no release yet.
set "EXTRACTIUM_TAG="
if not defined LANDED goto :eof
set "REST=%LANDED:*/releases/tag/=%"
if "%REST%"=="%LANDED%" goto :eof
set "EXTRACTIUM_TAG=%REST%"
goto :eof

:handover
REM Hand over to the copy of this script inside the checkout, which finds
REM the lock file and the package beside itself. The settings file stays
REM relative to the folder you ran this from.
call "%EXTRACTIUM_DIR%\run.bat" %*
exit /b %errorlevel%

:environment

REM ### Create the environment ###

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
if exist "%VENV_PYTHON%" if not defined FREE_THREADED_ONLY call :renew_free_threaded_venv
if not exist "%VENV_PYTHON%" (
    echo Creating a virtual environment in %VENV_DIR% ...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Could not create a virtual environment. Install Python 3.10 or newer, or set PYTHON to its path.
        exit /b 1
    )
)

REM ### Install pinned dependencies ###

REM The lock file carries a hash for every package, so pip refuses anything
REM whose contents do not match what was locked. A free-threaded Python
REM installs from a copy of it without the code parsers, which have no
REM wheels for that build; everything else keeps its hash.
set "LOCK=%HERE%\requirements-lock.txt"
"%VENV_PYTHON%" -c "import sys, sysconfig; sys.exit(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)" >nul 2>&1
if errorlevel 1 (
    echo This Python is the free-threaded build, which cannot use the code parsers' wheels.
    echo Installing without them: code files are still recorded by name, language, and length,
    echo but what they define is not read. Install a standard Python from python.org for that.
    set "LOCK=%VENV_DIR%\requirements-lock-without-parsers.txt"
    "%VENV_PYTHON%" "%HERE%\tools\lock_without_parsers.py" "%HERE%\requirements-lock.txt" "%VENV_DIR%\requirements-lock-without-parsers.txt"
    if errorlevel 1 exit /b 1
)

echo Installing pinned dependencies ...
"%VENV_PYTHON%" -m pip install --quiet --upgrade pip
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install --quiet --require-hashes -r "%LOCK%"
if errorlevel 1 exit /b 1

REM Installed without dependencies, because the line above already put the
REM exact locked versions in place.
"%VENV_PYTHON%" -m pip install --quiet --no-deps -e "%HERE%"
if errorlevel 1 exit /b 1

REM The build runs through the command the install just placed in the
REM environment, and not through the interpreter's -m flag on the
REM extractium.cli module. The module form puts the folder you ran this
REM script from at the front of the import path, so a folder named
REM "extractium" sitting there is imported in place of the installed
REM package and the build stops before it starts.
set "VENV_EXTRACTIUM=%VENV_DIR%\Scripts\extractium.exe"

REM ### Write a first settings file ###

REM With no settings file and no arguments, this is a first run: ask for
REM the name, the short name, and the website, then build with a page
REM limit so a pattern broader than intended costs seconds.
set "FIRST_RUN=0"
if "%~1"=="" if not exist "%CONFIG%" (
    echo.
    echo There is no %CONFIG% yet, so a few questions first.
    "%VENV_EXTRACTIUM%" init --output "%CONFIG%"
    if errorlevel 1 exit /b %errorlevel%
    set "FIRST_RUN=1"
)

REM ### Run the build ###

echo.
if not "%~1"=="" (
    "%VENV_EXTRACTIUM%" build %*
) else if "%FIRST_RUN%"=="1" (
    echo Building from %CONFIG%, limited to 25 pages for this first run ...
    "%VENV_EXTRACTIUM%" build --config "%CONFIG%" --max-pages 25
) else (
    echo Building from %CONFIG% ...
    "%VENV_EXTRACTIUM%" build --config "%CONFIG%"
)
if errorlevel 1 exit /b %errorlevel%

REM ### Say what to do next ###

echo.
echo Build finished. The summary above lists every file that was written.
echo.
if "%FIRST_RUN%"=="1" (
    echo This first run stopped at 25 pages. Open dist\llms.txt to see which pages
    echo were indexed. When the list looks right, run this script again to build
    echo the whole site. To change what is crawled, edit %CONFIG%.
    echo.
)
echo To publish the result:
echo   1. Add those files to git:   git add ^<output folder^>
echo   2. Commit them:              git commit -m "Rebuild the knowledge index"
echo   3. Push:                     git push
echo.
echo Do not commit the .venv folder or the .kb_cache folder. The cache only
echo saves time on the next run; deleting it is always safe.

endlocal
