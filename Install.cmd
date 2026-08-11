@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "EXE=%ROOT%SpotifyVoiceBasic.exe"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
set "BUILD=%ROOT%.build-temp"
set "APPDIR=%ROOT%"
set "DEPS=%ROOT%BuildCache\deps"
set "MODELS=%ROOT%ModelCache"
set "MODEL_EN=%MODELS%\vosk-model-small-en-us-0.15"
set "MODEL_RU=%MODELS%\vosk-model-small-ru-0.22"
set "OLD_MODEL_EN=%ROOT%..\..\work\dist2\SpotifyVoiceBasic\_internal\model-en"
set "OLD_MODEL_RU=%ROOT%..\..\work\dist2\SpotifyVoiceBasic\_internal\model-ru"

if not exist "%PYTHON%" (
  echo Python 3.14 was not found:
  echo %PYTHON%
  pause
  exit /b 1
)

if 1==1 (
  echo Building SpotifyVoiceBasic.exe. This can take several minutes...
  if not exist "%BUILD%" mkdir "%BUILD%"
  if not exist "%DEPS%" mkdir "%DEPS%"
  if not exist "%MODELS%" mkdir "%MODELS%"

  if not exist "%MODEL_EN%\am\final.mdl" if exist "%OLD_MODEL_EN%\am\final.mdl" (
    echo Reusing the English model already found on this PC...
    xcopy "%OLD_MODEL_EN%" "%MODEL_EN%\" /e /i /q /y >nul
  )
  if not exist "%MODEL_EN%\am\final.mdl" (
    echo Downloading English speech model...
    curl.exe --insecure --fail --location --output "%BUILD%\model-en.zip" "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    if errorlevel 1 goto download_error
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%BUILD%\model-en.zip' -DestinationPath '%MODELS%' -Force"
    if errorlevel 1 goto build_error
  )

  if not exist "%MODEL_RU%\am\final.mdl" if exist "%OLD_MODEL_RU%\am\final.mdl" (
    echo Reusing the Russian model already found on this PC...
    xcopy "%OLD_MODEL_RU%" "%MODEL_RU%\" /e /i /q /y >nul
  )
  if not exist "%MODEL_RU%\am\final.mdl" (
    echo Downloading Russian speech model...
    curl.exe --insecure --fail --location --output "%BUILD%\model-ru.zip" "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
    if errorlevel 1 goto download_error
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%BUILD%\model-ru.zip' -DestinationPath '%MODELS%' -Force"
    if errorlevel 1 goto build_error
  )

  if not exist "%MODEL_EN%\am\final.mdl" goto download_error
  if not exist "%MODEL_RU%\am\final.mdl" goto download_error
  call :cleanup_old_models

  if not exist "%DEPS%\PyInstaller" (
    echo Installing build tools...
    "%PYTHON%" -m pip install --target "%DEPS%" pyinstaller vosk sounddevice --no-cache-dir
    if errorlevel 1 goto build_error
  )
  if not exist "%DEPS%\pystray" (
    echo Installing system tray support...
    "%PYTHON%" -m pip install --target "%DEPS%" pystray pillow --no-cache-dir
    if errorlevel 1 goto build_error
  )

  call :package_exe
  if errorlevel 1 goto build_error
  rmdir /s /q "%BUILD%"
)

taskkill /f /im SpotifyVoiceBasic.exe >nul 2>nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$target='%EXE%'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Spotify Voice Basic.lnk')); $s.TargetPath=$target; $s.WorkingDirectory='%ROOT%'; $s.WindowStyle=7; $s.Save(); Start-Process $target -WindowStyle Hidden"
if errorlevel 1 goto install_error
echo Spotify Voice Basic was built, installed, and started.
timeout /t 5 >nul
exit /b 0

:download_error
echo.
echo Speech model download failed. Check your internet connection.
pause
exit /b 1

:build_error
echo.
echo EXE build failed. Review the messages above and try again.
pause
exit /b 1

:install_error
echo.
echo Installation failed.
pause
exit /b 1

:package_exe
if exist "%EXE%" del /f /q "%EXE%"
set "PYTHONPATH=%DEPS%"
set "SPOTIFY_BUILD_DEPS=%DEPS%"
set "SPOTIFY_MODEL_EN=%MODEL_EN%"
set "SPOTIFY_MODEL_RU=%MODEL_RU%"
set "SPOTIFY_BUILD_DIST=%ROOT%"
set "SPOTIFY_BUILD_WORK=%BUILD%\work"
echo Packaging the EXE...
"%PYTHON%" "%ROOT%spotify_voice.py" --write-spec "%BUILD%\SpotifyVoiceBasic.spec"
if errorlevel 1 exit /b 1
if not exist "%BUILD%\SpotifyVoiceBasic.spec" (
  echo Spec file was not created: %BUILD%\SpotifyVoiceBasic.spec
  exit /b 1
)
echo Using spec: %BUILD%\SpotifyVoiceBasic.spec
"%PYTHON%" "%ROOT%spotify_voice.py" --package-spec "%BUILD%\SpotifyVoiceBasic.spec"
exit /b %ERRORLEVEL%

:cleanup_old_models
echo Removing old duplicate speech models...
for %%D in (dist dist-liked dist-prefix dist2) do (
  if exist "%ROOT%..\..\work\%%D\SpotifyVoiceBasic\_internal\model-en" rmdir /s /q "%ROOT%..\..\work\%%D\SpotifyVoiceBasic\_internal\model-en"
  if exist "%ROOT%..\..\work\%%D\SpotifyVoiceBasic\_internal\model-ru" rmdir /s /q "%ROOT%..\..\work\%%D\SpotifyVoiceBasic\_internal\model-ru"
)
exit /b 0
