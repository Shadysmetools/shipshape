@echo off
rem qa: the one command on Windows cmd. Usage: qa demo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-qa.ps1" %*
