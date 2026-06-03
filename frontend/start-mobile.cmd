@echo off
setlocal
set "ROOT=%~dp0"
set "NODE=C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
set "PATH=%ROOT%node_modules\.bin;C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;%PATH%"
cd /d "%ROOT%"
echo.
echo Starting mobile/LAN preview...
echo Use your computer IPv4 address on the phone, for example:
echo http://YOUR-COMPUTER-IP:5173/
echo.
"%NODE%" node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173
