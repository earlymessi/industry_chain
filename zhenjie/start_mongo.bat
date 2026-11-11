@echo off
setlocal
cd /d "%~dp0"

set MONGOD=%~dp0mongodb-portable\mongodb-win32-x86_64-windows-7.0.28\bin\mongod.exe
set DBPATH=%~dp0mongo_data
set LOGDIR=%~dp0mongo_logs
set LOGFILE=%LOGDIR%\mongod.log

if not exist "%MONGOD%" (
  echo [ERROR] 未找到便携版 mongod: %MONGOD%
  exit /b 1
)

mkdir "%DBPATH%" 2>nul
mkdir "%LOGDIR%" 2>nul

echo Starting MongoDB on 127.0.0.1:27017 ...
start "mongod-zhenjie" /MIN "%MONGOD%" --dbpath "%DBPATH%" --bind_ip 127.0.0.1 --port 27017 --logpath "%LOGFILE%"
timeout /t 3 /nobreak >nul
echo Done. Log: %LOGFILE%
endlocal
