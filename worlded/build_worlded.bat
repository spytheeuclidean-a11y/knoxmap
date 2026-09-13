@echo off
rem Build the patched, headless PZWorldEd_cli.exe from source.
rem
rem Most people never need this: Setup.bat downloads the prebuilt compiler.
rem Needs: Visual Studio 2022 Build Tools (C++), Qt 5.14.2 msvc2017_64, git.
rem
rem   build_worlded.bat [path to Qt 5.14.2 msvc2017_64]
setlocal
set HERE=%~dp0
set QT=%~1
if "%QT%"=="" set QT=C:\Qt\5.14.2\msvc2017_64
set QMAKE=%QT%\bin\qmake.exe
set SRC=%HERE%src\PZ_Mapping_Tools
set OUT=%HERE%build
set COMMIT=4e86b80c505b3d77a2fb5f5675b752da966306f6

for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VS=%%i
if not defined VS (echo Visual Studio C++ build tools not found. & exit /b 1)
if not exist "%QMAKE%" (echo qmake not found at %QMAKE% - pass your Qt folder as the first argument. & exit /b 1)

if not exist "%SRC%" (
  git clone https://github.com/Unjammer/PZ_Mapping_Tools.git "%SRC%" || exit /b 2
)
git -C "%SRC%" checkout --quiet %COMMIT% || exit /b 2
git -C "%SRC%" checkout --quiet -- WorldEd/src/editor/main.cpp WorldEd/src/editor/lotfilesmanager256.h
python "%HERE%patch_worlded_cli.py" "%SRC%" || exit /b 3

call "%VS%\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 || exit /b 4
if not exist "%OUT%" mkdir "%OUT%"
cd /d "%OUT%" || exit /b 4
"%QMAKE%" "%SRC%\WorldEd\PZWorldEd.pro" -spec win32-msvc CONFIG+=release || exit /b 5
nmake || exit /b 6

copy /y "%OUT%\PZWorldEd.exe" "%OUT%\PZWorldEd_cli.exe" >nul
echo.
echo Built %OUT%\PZWorldEd_cli.exe
echo Copy it into the bin folder of PZ Mapping Tools (release 43.00B260909).
