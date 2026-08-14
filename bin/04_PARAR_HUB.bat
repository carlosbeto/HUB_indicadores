@echo off
setlocal
title Parar HUB Indicadores
color 0C

for %%I in ("%~dp0..") do set "HUB_ROOT=%%~fI"

set "HUB_APP=%HUB_ROOT%\code\hub\app.py"
set "PID="

echo.
echo ============================================================
echo               PARAR HUB INDICADORES - v1.0
echo ============================================================
echo.
echo Instalacao:
echo %HUB_ROOT%
echo.
echo Procurando o processo principal do HUB...
echo.

for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$app=$env:HUB_APP; $processos=@((Get-CimInstance Win32_Process).Where({$_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine -like ('*'+$app+'*')})); if($processos.Count -gt 0){$ids=@($processos.ProcessId); $principais=@($processos.Where({$ids -notcontains $_.ParentProcessId})); if($principais.Count -gt 0){$principal=$principais[0]}else{$principal=$processos[0]}; [Console]::WriteLine([int]$principal.ProcessId)}"') do set "PID=%%P"

if not defined PID (
    echo Status.............: NAO ESTA EM EXECUCAO
    echo.
    echo Nenhuma acao e necessaria.
    echo.
    pause
    exit /b
)

echo Status.............: EXECUTANDO
echo PID principal.: %PID%
echo.

choice /C SN /N /M "Deseja realmente encerrar o HUB? [S/N]: "

if errorlevel 2 (
    echo.
    echo Operacao cancelada.
    echo.
    pause
    exit /b
)

echo.
echo Encerrando HUB...
echo.

taskkill /PID %PID% /T /F >nul 2>&1

if errorlevel 1 (
    echo [ERRO] Nao foi possivel encerrar o HUB.
) else (
    echo [OK] HUB encerrado com sucesso.
)

echo.
pause
endlocal