@echo off
setlocal
set "ROOT=%~dp0"
set "NODE=C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
set "PATH=%ROOT%node_modules\.bin;C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;%PATH%"
cd /d "%ROOT%"
"%NODE%" node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173
