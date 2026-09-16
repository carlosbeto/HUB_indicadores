@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ================================================================
rem INICIALIZACAO DO APP - ANALISE DE RESSUPRIMENTO
rem
rem Este arquivo apenas sobe o Streamlit. Ele nao executa nenhum ETL.
rem Para encerrar o aplicativo, use Ctrl+C nesta janela.
rem ================================================================

cd /d "%~dp0"
title App - Analise de Ressuprimento - Porta 8504

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

echo ================================================================
echo ANALISE DE RESSUPRIMENTO - STREAMLIT
echo ================================================================
echo Pasta: %CD%
echo Python: %PYTHON_EXE%
echo Porta: 8504
echo Acesso local: http://localhost:8504
echo Acesso pela rede: http://%COMPUTERNAME%:8504
echo.
echo Para encerrar, pressione Ctrl+C nesta janela.
echo.

if not exist "%PYTHON_EXE%" goto :erro_venv

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 goto :erro_python

if not exist "app.py" goto :erro_app
if not exist "data_db\ressuprimento.sqlite" goto :erro_banco

"%PYTHON_EXE%" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8504
set "CODIGO_SAIDA=%ERRORLEVEL%"

if "%CODIGO_SAIDA%"=="0" exit /b 0

echo.
echo O Streamlit foi encerrado com codigo %CODIGO_SAIDA%.
echo Verifique se a porta 8504 ja esta em uso ou se houve erro no aplicativo.
echo.
pause
exit /b %CODIGO_SAIDA%

:erro_python
echo.
echo ERRO: Python nao foi encontrado ou nao pode ser executado.
goto :falha

:erro_venv
echo.
echo ERRO: ambiente virtual nao encontrado em:
echo %PYTHON_EXE%
echo Crie o .venv e instale requirements.txt antes de iniciar o app.
goto :falha

:erro_app
echo.
echo ERRO: app.py nao foi encontrado em %CD%.
goto :falha

:erro_banco
echo.
echo ERRO: data_db\ressuprimento.sqlite nao foi encontrado.
goto :falha

:falha
echo.
pause
exit /b 1
