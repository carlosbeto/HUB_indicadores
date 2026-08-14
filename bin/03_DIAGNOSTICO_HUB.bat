@echo off
setlocal
title Diagnostico - HUB Indicadores
color 0B

rem O BAT esta na pasta bin. A raiz do projeto fica um nivel acima.
for %%I in ("%~dp0..") do set "HUB_ROOT=%%~fI"
set "HUB_APP=%HUB_ROOT%\code\hub\app.py"

echo.
echo ============================================================
echo                 DIAGNOSTICO - HUB INDICADORES
echo ============================================================
echo.
echo Instalacao verificada:
echo %HUB_ROOT%
echo.
echo Procurando a execucao desta instalacao do HUB...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$app = $env:HUB_APP; $processos = @(Get-CimInstance Win32_Process).Where({$_.CommandLine -and $_.CommandLine -like ('*' + $app + '*')}); if ($processos.Count -eq 0) { Write-Host '[AVISO] O HUB desta instalacao nao esta em execucao.' -ForegroundColor Yellow } else { Write-Host ('[OK] Foram encontrados ' + $processos.Count + ' processo(s):') -ForegroundColor Green; Write-Host ''; foreach ($p in $processos) { Write-Host ('PID principal/filho: ' + $p.ProcessId); Write-Host ('Processo pai:       ' + $p.ParentProcessId); Write-Host ('Executavel:         ' + $p.Name); Write-Host ('Comando:            ' + $p.CommandLine); Write-Host '' } }"

echo.
echo ============================================================
echo Este diagnostico nao encerrou nenhum processo.
echo ============================================================
echo.
pause

endlocal