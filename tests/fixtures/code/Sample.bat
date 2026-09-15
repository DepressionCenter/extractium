@echo off
REM This file is part of Extractium(TM)
REM tests/fixtures/code/Sample.bat
REM Author(s): Gabriel Mongefranco.
REM Created: 2026-09-15
REM Last Modified: 2026-09-15
REM Summary: A synthetic batch file for the code-analysis tests: two
REM labels, one documented on the line after it, and a handful of commands.
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
set "HERE=%~dp0"
if not defined CONFIG set "CONFIG=config.yaml"
call :build "%CONFIG%"
if errorlevel 1 exit /b 1
goto :end

:build
REM Runs one build from the settings file named as the first argument.
echo Building from %1 ...
python -m extractium.cli build --config %1
exit /b 0

:end
endlocal
