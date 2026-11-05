@echo off
rem Installs AFH's terminal app from Command Prompt. It runs the PowerShell installer, which does the work.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://agentflowharness.com/install.ps1 | iex"
