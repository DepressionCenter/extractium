@echo off
REM This file is part of Extractium(TM)
REM install.bat
REM Author(s): Gabriel Mongefranco.
REM Created: 2026-09-30
REM Last Modified: 2026-09-30
REM Summary: Installs Extractium on Windows for the person running it, with
REM no admin rights, into one folder that holds its own Python, the
REM packages, the command, and the model cache. Beside a ready Extractium
REM folder, as in the release zip, it copies that folder under the profile
REM with no download. Inside a checkout it installs the checkout. On its
REM own it downloads the release and builds the folder: uv first, with its
REM hash checked, then a Python already on this computer. It then puts the
REM command on PATH and Extractium in the Start menu. "--portable" builds
REM the folder beside this script and changes nothing else; "--update"
REM moves an install to a newer release; "--uninstall" removes it.
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

REM The uv release this script downloads, and the SHA-256 of its Windows
REM archives as published beside them. Move the version and both hashes
REM together, after reading the release notes. A download whose hash
REM differs is refused.
set "UV_VERSION=0.12.20"
set "UV_SHA256_X86_64_WINDOWS=95f9bc30fbb3574d276e28ac4a6de932d25153645853d13da8c21eec3bc88d06"
set "UV_SHA256_AARCH64_WINDOWS=b6bd9218855591742ffd3b00fcf2044b4d2fb6446b6a3545e0dfee447e950388"

REM The Python uv installs into the folder. A standard build: the
REM free-threaded one cannot use the code parsers' wheels.
set "PYTHON_VERSION=3.12.12"

REM Where Extractium is downloaded from, and which release. "latest" is
REM looked up as the newest published release; --version TAG pins one.
if not defined EXTRACTIUM_REPO set "EXTRACTIUM_REPO=https://github.com/DepressionCenter/extractium"
set "EXTRACTIUM_REF=latest"

REM Where this script lives, with no trailing backslash.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

REM This script's own full path, taken here because %~f0 inside a called
REM label no longer names the script.
set "SELF=%~f0"

REM Where the folder goes for a per-user install. A portable install puts
REM it beside this script instead.
set "HOME_DIR=%LOCALAPPDATA%\Extractium"

REM A double-clicked window closes when the script ends, so it pauses
REM first when it was started that way.
set "PAUSE_AT_END="
echo %cmdcmdline% | find /i "%~f0" >nul 2>nul && set "PAUSE_AT_END=1"

call :main %*
set "CODE=%errorlevel%"
if defined PAUSE_AT_END (
    echo.
    pause
)
endlocal & exit /b %CODE%


:main
REM ### Flags ###

set "MODE=install"
set "PORTABLE="
set "EDITABLE="
set "HOME_GIVEN="
:flags
if "%~1"=="" goto :flags_done
if /i "%~1"=="--portable" set "PORTABLE=1"
if /i "%~1"=="--editable" set "EDITABLE=1"
if /i "%~1"=="--update" set "MODE=update"
if /i "%~1"=="--uninstall" set "MODE=uninstall"
if /i "%~1"=="--version" (
    set "EXTRACTIUM_REF=%~2"
    shift
)
if /i "%~1"=="--home" (
    set "HOME_GIVEN=%~f2"
    shift
)
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
shift
goto :flags
:flags_done

if defined PORTABLE set "HOME_DIR=%HERE%\Extractium"
if defined HOME_GIVEN set "HOME_DIR=%HOME_GIVEN%"

REM Inside a checkout, a folder named Extractium beside this script is
REM the package folder itself on a disk that ignores case, so a portable
REM build there needs --home to say where the folder goes.
if defined PORTABLE if not defined HOME_GIVEN if exist "%HERE%\pyproject.toml" (
    echo Inside a checkout, a portable build needs --home DIR to say where the Extractium folder goes,
    echo because a folder of that name beside this script would be the package folder on this disk.
    exit /b 2
)

REM Every uv call trusts the certificates this computer trusts, so a
REM corporate proxy that inspects traffic does not stop the download,
REM keeps its cache outside the folder, and copies files into the folder
REM rather than linking them, so the folder can move.
set "UV_SYSTEM_CERTS=1"
set "UV_LINK_MODE=copy"
set "UV_CACHE_DIR=%TEMP%\extractium-uv-cache"
set "UV_PYTHON_INSTALL_DIR=%HOME_DIR%\python"

REM ### Tell the situation apart ###

if "%MODE%"=="uninstall" goto :uninstall
if "%MODE%"=="update" goto :update

REM A ready folder beside this script, as the release zip holds: copied
REM under the profile, with nothing downloaded.
if exist "%HERE%\Extractium\bin\extractium.cmd" if not defined PORTABLE goto :copy_ready

REM Inside a checkout, the checkout is what gets installed.
if exist "%HERE%\pyproject.toml" (
    set "SOURCE=%HERE%"
    goto :have_source
)

REM On its own: the release is downloaded first.
call :download_release
if errorlevel 1 exit /b 1

:have_source
set "LOCK=%SOURCE%\requirements-lock.txt"
set "INSTALL_PY=%SOURCE%\extractium\install.py"
if not exist "%INSTALL_PY%" (
    echo The folder %SOURCE% does not hold this release's installer. Check --version.
    exit /b 1
)
if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"

REM ### Step 1: uv ###

set "UV="
set "PYTHON="
call :get_uv
if errorlevel 1 goto :step_3

REM ### Step 2: a Python that uv manages ###

REM The Python goes into the folder and nowhere else: no launcher in the
REM profile's bin folder, and no entry in the Windows registry.
echo Installing Python %PYTHON_VERSION% into %HOME_DIR%\python ...
"%UV%" python install "%PYTHON_VERSION%" --install-dir "%HOME_DIR%\python" --no-bin --no-registry
if errorlevel 1 (
    echo The managed Python could not be downloaded. Looking for a Python already on this computer for uv to use.
    call :uv_with_machine_python
    if errorlevel 1 goto :step_3
    goto :finish
)
for /f "delims=" %%P in ('dir /b /s "%HOME_DIR%\python\python.exe" 2^>nul') do if not defined PYTHON set "PYTHON=%%P"
if not defined PYTHON (
    echo uv installed Python but no python.exe was found under %HOME_DIR%\python.
    goto :step_3
)
goto :finish

:step_3
REM ### Step 3: a Python already on this computer, with pip ###

echo.
echo Step 3: using a Python already on this computer. An install made this way cannot be moved.
set "UV="
set "CHOSEN="
set "TRY_MODE=standard"
if defined PYTHON_EXE call :try_python "%PYTHON_EXE%"
if not defined CHOSEN call :choose_python
if not defined CHOSEN (
    echo No Python 3.10 or newer was found on this computer.
    call :offer_winget
    goto :step_4
)
echo Making a virtual environment in %HOME_DIR%\venv with %CHOSEN% ...
if exist "%HOME_DIR%\venv" rmdir /s /q "%HOME_DIR%\venv"
%CHOSEN% -m venv "%HOME_DIR%\venv"
if errorlevel 1 (
    echo The virtual environment could not be made.
    goto :step_4
)
set "PYTHON=%HOME_DIR%\venv\Scripts\python.exe"
"%PYTHON%" -m pip install --quiet --upgrade pip
if errorlevel 1 goto :step_4
goto :finish

:step_4
REM ### Step 4: stop, and say what to ask for ###

echo.
echo Extractium could not be installed on this computer without help.
echo   Step 1, uv, could not be downloaded or could not start.
echo   Step 3, a Python already on this computer, was not found or could not make an environment.
echo Ask IT for one of these:
echo   - permission to run programs from %LOCALAPPDATA%, which is what uv and its Python need; or
echo   - a standard Python 3.10 or newer installed for you, from python.org or the Microsoft Store.
echo Then run this script again.
exit /b 1

:finish
REM ### Install the packages and finish ###

set "FINISH_ARGS=--home "%HOME_DIR%" --python "%PYTHON%" --source "%SOURCE%" --lock "%LOCK%" --installer "%SELF%""
if defined UV set "FINISH_ARGS=%FINISH_ARGS% --uv "%UV%""
if defined PORTABLE set "FINISH_ARGS=%FINISH_ARGS% --portable"
if defined EDITABLE set "FINISH_ARGS=%FINISH_ARGS% --editable"
if /i not "%EXTRACTIUM_REF%"=="latest" set "FINISH_ARGS=%FINISH_ARGS% --version "%EXTRACTIUM_REF%""
echo Installing the packages from the lock file, with every hash checked ...
"%PYTHON%" -I "%INSTALL_PY%" finish %FINISH_ARGS%
if errorlevel 1 exit /b 1
call :cleanup_download
exit /b 0

:copy_ready
REM ### A ready folder beside this script ###

for /f "delims=" %%P in ('dir /b /s "%HERE%\Extractium\python\python.exe" 2^>nul') do if not defined PYTHON set "PYTHON=%%P"
if not defined PYTHON set "PYTHON=%HERE%\Extractium\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo The Extractium folder beside this script holds no Python. Download the release zip again.
    exit /b 1
)
echo Copying %HERE%\Extractium to %HOME_DIR% ...
"%PYTHON%" -I -m extractium.install copy --from "%HERE%\Extractium" --home "%HOME_DIR%" --installer "%SELF%"
exit /b %errorlevel%

:update
REM ### Move an install to a newer release ###

call :find_home
if errorlevel 1 exit /b 1
if exist "%HERE%\pyproject.toml" (
    set "SOURCE=%HERE%"
) else (
    call :download_release
    if errorlevel 1 exit /b 1
)
set "LOCK=%SOURCE%\requirements-lock.txt"
set "INSTALL_PY=%SOURCE%\extractium\install.py"
for /f "delims=" %%P in ('dir /b /s "%HOME_DIR%\python\python.exe" 2^>nul') do if not defined PYTHON set "PYTHON=%%P"
if not defined PYTHON set "PYTHON=%HOME_DIR%\venv\Scripts\python.exe"
set "UPDATE_ARGS=--home "%HOME_DIR%" --source "%SOURCE%" --lock "%LOCK%""
if /i not "%EXTRACTIUM_REF%"=="latest" set "UPDATE_ARGS=%UPDATE_ARGS% --version "%EXTRACTIUM_REF%""
echo Updating %HOME_DIR% ...
"%PYTHON%" -I "%INSTALL_PY%" update %UPDATE_ARGS%
if errorlevel 1 exit /b 1
copy /y "%SOURCE%\install.bat" "%HOME_DIR%\install.bat" >nul
call :cleanup_download
exit /b 0

:uninstall
REM ### Remove an install ###

call :find_home
if errorlevel 1 exit /b 1
set "ANSWER=n"
set /p "ANSWER=Remove Extractium from %HOME_DIR%, its PATH entry, and its Start menu entry? [y/N]: "
if /i not "%ANSWER:~0,1%"=="y" (
    echo Nothing was removed.
    exit /b 0
)
for /f "delims=" %%P in ('dir /b /s "%HOME_DIR%\python\python.exe" 2^>nul') do if not defined PYTHON set "PYTHON=%%P"
if not defined PYTHON set "PYTHON=%HOME_DIR%\venv\Scripts\python.exe"
if exist "%PYTHON%" "%PYTHON%" -I -m extractium.install uninstall --home "%HOME_DIR%"
rmdir /s /q "%HOME_DIR%"
echo Removed %HOME_DIR%.
exit /b 0

:find_home
REM The folder an update or an uninstall works on: this script's own
REM folder when it is the copy kept inside one, the folder beside it,
REM or the per-user one.
if exist "%HERE%\bin\extractium.cmd" (
    set "HOME_DIR=%HERE%"
    exit /b 0
)
if exist "%HERE%\Extractium\bin\extractium.cmd" (
    set "HOME_DIR=%HERE%\Extractium"
    exit /b 0
)
if exist "%HOME_DIR%\bin\extractium.cmd" exit /b 0
echo No Extractium install was found beside this script or in %HOME_DIR%.
exit /b 1

:get_uv
REM Downloads uv at the pinned version, checks its hash, unpacks it into
REM the folder, and asks it for its version. A uv already in the folder
REM that starts is kept.
set "UV=%HOME_DIR%\uv.exe"
if exist "%UV%" (
    "%UV%" --version >nul 2>nul
    if not errorlevel 1 exit /b 0
)
set "ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "ARCH=%PROCESSOR_ARCHITEW6432%"
if /i "%ARCH%"=="ARM64" (
    set "UV_ASSET=uv-aarch64-pc-windows-msvc.zip"
    set "UV_SHA256=%UV_SHA256_AARCH64_WINDOWS%"
) else (
    set "UV_ASSET=uv-x86_64-pc-windows-msvc.zip"
    set "UV_SHA256=%UV_SHA256_X86_64_WINDOWS%"
)
set "UV_URL=https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_ASSET%"
set "UV_STAGING=%TEMP%\extractium-uv-%RANDOM%"
mkdir "%UV_STAGING%"
echo Step 1: downloading uv %UV_VERSION% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%UV_URL%' -OutFile '%UV_STAGING%\uv.zip'"
if errorlevel 1 (
    echo uv could not be downloaded from %UV_URL%. Check the network.
    rmdir /s /q "%UV_STAGING%"
    exit /b 1
)
call :sha256_of "%UV_STAGING%\uv.zip"
if /i not "%GOT_SHA256%"=="%UV_SHA256%" (
    echo The uv download does not match the SHA-256 this script expects, so it was not used.
    echo   expected %UV_SHA256%
    echo   got      %GOT_SHA256%
    rmdir /s /q "%UV_STAGING%"
    exit /b 1
)
call :unzip "%UV_STAGING%\uv.zip" "%UV_STAGING%\unpacked"
if errorlevel 1 (
    echo The uv archive could not be unpacked.
    rmdir /s /q "%UV_STAGING%"
    exit /b 1
)
set "UV_EXE="
for /f "delims=" %%F in ('dir /b /s "%UV_STAGING%\unpacked\uv.exe" 2^>nul') do if not defined UV_EXE set "UV_EXE=%%F"
if not defined UV_EXE (
    echo The uv archive held no uv.exe.
    rmdir /s /q "%UV_STAGING%"
    exit /b 1
)
copy /y "%UV_EXE%" "%UV%" >nul
rmdir /s /q "%UV_STAGING%"
"%UV%" --version
if errorlevel 1 (
    echo uv is in %HOME_DIR% but could not start. A policy on this computer may refuse programs run
    echo from a user folder; ask IT whether that is so.
    exit /b 1
)
exit /b 0

:sha256_of
REM The SHA-256 of one file, lowercase, in GOT_SHA256. certutil ships
REM with every Windows and needs no PowerShell module; PowerShell's own
REM cmdlet is the second try, for a certutil that has been removed.
set "GOT_SHA256="
for /f "delims=" %%H in ('certutil -hashfile "%~1" SHA256 ^| findstr /v /i "hash CertUtil"') do if not defined GOT_SHA256 set "GOT_SHA256=%%H"
if defined GOT_SHA256 set "GOT_SHA256=%GOT_SHA256: =%"
if not defined GOT_SHA256 for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-FileHash -Algorithm SHA256 -Path '%~1').Hash.ToLower()"`) do set "GOT_SHA256=%%H"
goto :eof

:unzip
REM Unpacks a zip into a folder. tar ships with Windows 10 and later and
REM needs no PowerShell module; Expand-Archive is the second try.
if not exist "%~2" mkdir "%~2"
tar -xf "%~1" -C "%~2" 2>nul
if not errorlevel 1 goto :eof
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%~1' -DestinationPath '%~2' -Force"
goto :eof

:uv_with_machine_python
REM When the managed Python download is refused, uv makes a virtual
REM environment on a Python already on this computer. That install
REM cannot be moved, because the environment records where it was made.
set "FOUND="
for /f "delims=" %%P in ('"%UV%" python find ">=3.10" 2^>nul') do if not defined FOUND set "FOUND=%%P"
if not defined FOUND exit /b 1
if exist "%HOME_DIR%\venv" rmdir /s /q "%HOME_DIR%\venv"
"%UV%" venv --python "%FOUND%" "%HOME_DIR%\venv"
if errorlevel 1 exit /b 1
set "PYTHON=%HOME_DIR%\venv\Scripts\python.exe"
exit /b 0

:choose_python
REM Tries the launcher's default, then each release from newest to oldest,
REM then a python on the path, and keeps the first standard build that is
REM 3.10 or newer. Set PYTHON_EXE to the path of one to try it first.
set "TRY_MODE=standard"
for %%C in ("py -3" "py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10" "python") do if not defined CHOSEN call :try_python %%~C
goto :eof

:try_python
%* -c "import sys, sysconfig; sys.exit(0 if sys.version_info >= (3, 10) and not sysconfig.get_config_var('Py_GIL_DISABLED') else 1)" >nul 2>&1
if not errorlevel 1 set "CHOSEN=%*"
goto :eof

:offer_winget
REM A packager can supply Python where the person may install software.
REM The command is printed and run only on a yes; nothing is elevated.
where winget >nul 2>nul
if errorlevel 1 (
    echo winget is not available here, so Python cannot be installed by this script.
    goto :eof
)
echo Python can be installed for your account with:
echo   winget install --id Python.Python.3.12 --scope user
set "ANSWER=n"
set /p "ANSWER=Run it now? [y/N]: "
if /i "%ANSWER:~0,1%"=="y" (
    winget install --id Python.Python.3.12 --scope user
    if not errorlevel 1 (
        set "CHOSEN="
        call :choose_python
    )
)
goto :eof

:download_release
REM Resolves "latest" to the newest release's tag through the redirect
REM GitHub serves, downloads that release's archive, and unpacks it into
REM a temporary folder that is removed once the install ends.
set "RELEASE_STAGING="
if /i not "%EXTRACTIUM_REF%"=="latest" goto :ref_known
set "LANDED="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $r = [Net.WebRequest]::Create('%EXTRACTIUM_REPO%/releases/latest'); $r.AllowAutoRedirect = $false; $r.GetResponse().Headers['Location']"`) do set "LANDED=%%L"
set "EXTRACTIUM_TAG="
if defined LANDED (
    set "REST=%LANDED:*/releases/tag/=%"
    if not "%REST%"=="%LANDED%" set "EXTRACTIUM_TAG=%REST%"
)
if not defined EXTRACTIUM_TAG (
    echo No published release was found at %EXTRACTIUM_REPO%/releases/latest. Pass --version with a tag.
    exit /b 1
)
set "EXTRACTIUM_REF=%EXTRACTIUM_TAG%"
:ref_known
set "ARCHIVE=%EXTRACTIUM_REPO%/archive/%EXTRACTIUM_REF%.zip"
set "RELEASE_STAGING=%TEMP%\extractium-release-%RANDOM%"
mkdir "%RELEASE_STAGING%"
echo Downloading Extractium %EXTRACTIUM_REF% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ARCHIVE%' -OutFile '%RELEASE_STAGING%\extractium.zip'"
if not errorlevel 1 call :unzip "%RELEASE_STAGING%\extractium.zip" "%RELEASE_STAGING%"
if errorlevel 1 (
    echo Extractium could not be downloaded from %ARCHIVE%. Check the network and --version.
    rmdir /s /q "%RELEASE_STAGING%"
    exit /b 1
)
set "SOURCE="
for /d %%D in ("%RELEASE_STAGING%\*") do if not defined SOURCE set "SOURCE=%%D"
if not defined SOURCE goto :bad_archive
if not exist "%SOURCE%\pyproject.toml" goto :bad_archive
exit /b 0
:bad_archive
echo The downloaded archive did not hold Extractium. Check --version ^(%EXTRACTIUM_REF%^).
rmdir /s /q "%RELEASE_STAGING%"
exit /b 1

:cleanup_download
if defined RELEASE_STAGING if exist "%RELEASE_STAGING%" rmdir /s /q "%RELEASE_STAGING%"
goto :eof

:help
echo Installs Extractium for your account, with no admin rights.
echo.
echo   install.bat                 Install, or copy the Extractium folder beside this script under your profile.
echo   install.bat --portable      Build the Extractium folder beside this script and change nothing else.
echo   install.bat --home DIR      Put the Extractium folder there instead. A portable build inside a checkout needs it.
echo   install.bat --update        Move an existing install to the newest release.
echo   install.bat --version TAG   Install, or update to, that release instead of the newest.
echo   install.bat --editable      In a checkout, run the code in the checkout (for developers).
echo   install.bat --uninstall     Remove the install, its PATH entry, and its Start menu entry.
exit /b 0
