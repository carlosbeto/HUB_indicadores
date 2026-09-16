@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ================================================================
rem ATUALIZACAO DAS BASES - ANALISE DE RESSUPRIMENTO (DEV)
rem
rem Este arquivo deve permanecer na raiz de analiseRessuprimento.
rem Ele cria um backup do SQLite e executa os tres ETLs de rotina.
rem ================================================================

cd /d "%~dp0"
title Atualizacao das bases - Analise de Ressuprimento

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=python"

rem Se futuramente o projeto possuir ambiente virtual proprio, ele sera
rem utilizado automaticamente. Caso contrario, permanece o Python do PATH.
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

set "DB_FILE=%CD%\data_db\ressuprimento.sqlite"
set "BACKUP_DIR=%CD%\data_db\backups"

echo ================================================================
echo ATUALIZACAO DAS BASES - ANALISE DE RESSUPRIMENTO
echo ================================================================
echo Pasta: %CD%
echo.

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 goto :erro_python

if not exist "%DB_FILE%" goto :erro_banco
if not exist "INPUT\MB51" goto :erro_mb51_pasta
if not exist "INPUT\BINMAT" goto :erro_binmat_pasta
if not exist "INPUT\VISAO_GERAL" goto :erro_visao_pasta

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
if errorlevel 1 goto :erro_backup

for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TIMESTAMP=%%I"
if not defined TIMESTAMP set "TIMESTAMP=sem_data_%RANDOM%"

set "BACKUP_FILE=%BACKUP_DIR%\ressuprimento_backup_%TIMESTAMP%_pre_etl.sqlite"

echo [1/4] Criando backup do banco...
copy /v /y "%DB_FILE%" "%BACKUP_FILE%" >nul
if errorlevel 1 goto :erro_backup
echo Backup criado: %BACKUP_FILE%
echo.

echo [2/4] Carregando movimentos MB51...
"%PYTHON_EXE%" etl\load_mb51.py
if errorlevel 1 goto :erro_mb51
echo.

echo [3/4] Carregando snapshot BINMAT mais recente...
"%PYTHON_EXE%" etl\load_binmat.py
if errorlevel 1 goto :erro_binmat
echo.

echo [4/4] Carregando snapshot VISAO_GERAL mais recente...
"%PYTHON_EXE%" etl\load_visao_geral.py
if errorlevel 1 goto :erro_visao
echo.

echo ================================================================
echo ATUALIZACAO CONCLUIDA COM SUCESSO
echo ================================================================
echo Backup anterior ao ETL:
echo %BACKUP_FILE%
echo.
pause
exit /b 0

:erro_python
echo.
echo ERRO: Python nao foi encontrado ou nao pode ser executado.
goto :falha

:erro_banco
echo.
echo ERRO: banco nao encontrado em:
echo %DB_FILE%
goto :falha

:erro_mb51_pasta
echo.
echo ERRO: pasta INPUT\MB51 nao encontrada.
goto :falha

:erro_binmat_pasta
echo.
echo ERRO: pasta INPUT\BINMAT nao encontrada.
goto :falha

:erro_visao_pasta
echo.
echo ERRO: pasta INPUT\VISAO_GERAL nao encontrada.
goto :falha

:erro_backup
echo.
echo ERRO: nao foi possivel criar o backup do banco.
goto :falha

:erro_mb51
echo.
echo ERRO: a carga MB51 falhou. As etapas seguintes nao foram executadas.
goto :falha

:erro_binmat
echo.
echo ERRO: a carga BINMAT falhou. A VISAO_GERAL nao foi executada.
goto :falha

:erro_visao
echo.
echo ERRO: a carga VISAO_GERAL falhou.
goto :falha

:falha
echo.
echo Consulte a mensagem apresentada acima antes de tentar novamente.
echo O backup anterior ao ETL foi preservado quando chegou a ser criado.
echo.
pause
exit /b 1