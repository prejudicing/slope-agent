@echo off
setlocal
set "ROOT=%~dp0"
start "GQP Backend 8000" cmd /k "%ROOT%backend\start-backend.cmd"
start "GQP Frontend 5173" cmd /k "%ROOT%frontend\start-dev.cmd"
echo Backend:  http://127.0.0.1:8000/api/health
echo Frontend: http://127.0.0.1:5173/
echo Mobile:   use http://YOUR-COMPUTER-IP:8000/ on the same Wi-Fi
