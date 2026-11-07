@echo off
REM Lanza Mango Bot en Windows con comprobaciones previas.
REM
REM   run.bat              arranca el bot (Ctrl+C para parar)
REM   run.bat --background lo deja en segundo plano (sobrevive al cerrar la ventana)
REM   run.bat --stop       detiene el bot
REM   run.bat --voices     descarga las voces locales gratis (Piper + Kokoro)
REM   run.bat --check      comprueba configuracion y APIs
REM   run.bat --security   comprueba que no haya claves en el proyecto

setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "PIDFILE=mango.pid"
set "TITULO=MangoBot"

if /I "%~1"=="--help"       goto ayuda
if /I "%~1"=="-h"           goto ayuda
if /I "%~1"=="--stop"       goto parar
if /I "%~1"=="--voices"     goto voces
if /I "%~1"=="--security"   goto seguridad
if /I "%~1"=="--check"      goto comprobar
if /I "%~1"=="-c"           goto comprobar
if /I "%~1"=="--background" goto fondo
if /I "%~1"=="-b"           goto fondo
goto arrancar

:ayuda
echo Uso de run.bat:
echo   run.bat              arranca el bot (Ctrl+C para parar)
echo   run.bat --background lo deja en segundo plano
echo   run.bat --stop       detiene el bot
echo   run.bat --voices     descarga las voces locales (Piper + Kokoro)
echo   run.bat --check      comprueba el .env y tus APIs
echo   run.bat --security   comprueba que no haya claves en el proyecto
exit /b 0

:comprobar_entorno
if not exist "%PY%" (
  echo [ERROR] No encuentro el entorno virtual .venv
  echo         Creelo asi:
  echo           py -3.12 -m venv .venv
  echo           .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
if not exist ".env" (
  echo [ERROR] Falta el archivo .env
  echo         Copialo y rellenalo:  copy .env.example .env
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 echo [AVISO] FFmpeg no esta en el PATH: no habra musica.
exit /b 0

:arrancar
call :comprobar_entorno || exit /b 1
echo Mango Bot arrancando... (Ctrl+C para parar)
"%PY%" bot.py
exit /b %errorlevel%

:comprobar
call :comprobar_entorno || exit /b 1
"%PY%" tests\check_apis.py
exit /b %errorlevel%

:seguridad
if not exist "%PY%" (
  echo [ERROR] No encuentro el entorno virtual .venv
  exit /b 1
)
"%PY%" tests\check_secrets.py
exit /b %errorlevel%

:voces
if not exist "%PY%" (
  echo [ERROR] No encuentro el entorno virtual .venv
  exit /b 1
)
"%PY%" -m mango.services.voices %2 %3 %4
exit /b %errorlevel%

:fondo
call :comprobar_entorno || exit /b 1
for /f %%i in ('powershell -NoProfile -Command "(Start-Process -FilePath '%PY%' -ArgumentList 'bot.py' -WindowStyle Hidden -PassThru).Id"') do set "BOTPID=%%i"
if not defined BOTPID (
  echo [ERROR] No pude lanzar el bot en segundo plano.
  exit /b 1
)
> "%PIDFILE%" echo %BOTPID%
echo Mango Bot en segundo plano ^(PID %BOTPID%^).
echo    Logs:  type mango.log   (o abrelo con tu editor)
echo    Parar: run.bat --stop
exit /b 0

:parar
set "BOTPID="
if exist "%PIDFILE%" (
  for /f "usebackq delims=" %%i in ("%PIDFILE%") do set "BOTPID=%%i"
)
if defined BOTPID (
  taskkill /PID %BOTPID% /F >nul 2>nul
  if errorlevel 1 (
    echo No habia ningun bot corriendo con ese PID.
  ) else (
    echo Mango Bot detenido.
  )
  del "%PIDFILE%" >nul 2>nul
  exit /b 0
)
echo No encuentro el archivo %PIDFILE%.
echo Si lo lanzaste en esta ventana, cierrala o pulsa Ctrl+C.
exit /b 1