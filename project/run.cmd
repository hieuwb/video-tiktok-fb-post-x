@echo off
REM Quick launcher. Usage: run [start|stop|restart|logs|status|find]
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
