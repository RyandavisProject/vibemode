@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0update-and-restart.ps1" %*
