from __future__ import annotations

import runpy
from pathlib import Path

import pytest


# O orquestrador é um script produtivo, não um módulo Python convencional.
# Usamos runpy para carregar suas funções sem disparar automaticamente main().
ETL_PATH = (
    Path(__file__).resolve().parents[2]
    / "code"
    / "analiseInventarios"
    / "scripts"
    / "etl_inventarios.py"
)

ETL = runpy.run_path(str(ETL_PATH))

run_step = ETL["run_step"]
main = ETL["main"]


def test_run_step_interrompe_etl_quando_script_falha(
    tmp_path,
):
    """
    Uma etapa com código de saída diferente de zero deve interromper
    imediatamente o ETL de Inventários.

    Esse contrato garante que o orquestrador não continue executando
    etapas posteriores quando uma etapa obrigatória falha.
    """

    script_falho = tmp_path / "script_falho.py"

    # O script temporário simula uma etapa produtiva que terminou com erro.
    # Usamos SystemExit(1) para reproduzir o mesmo contrato adotado pelo
    # loader quando uma fonte obrigatória está ausente.
    script_falho.write_text(
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        run_step(
            "[TESTE] Etapa com falha...",
            script_falho,
        )

    # run_step() deve transformar o retorno não-zero da etapa em uma
    # interrupção explícita do orquestrador.
    mensagem = str(exc_info.value)

    assert "[ERRO] Falha na etapa:" in mensagem
    assert "retorno=1" in mensagem


def test_main_nao_executa_etapas_apos_primeira_falha(
    monkeypatch,
):
    """
    O orquestrador deve trabalhar em modo fail-fast.

    Quando uma etapa obrigatória falha, nenhuma etapa posterior pode
    ser iniciada. Isso evita gerar snapshots, baselines ou KPIs sobre
    uma carga de contagens que não foi concluída corretamente.
    """

    etapas_executadas = []

    def run_step_controlado(step_name, script_path):
        """
        Substitui temporariamente run_step() para observar a sequência
        do orquestrador sem executar os scripts produtivos de verdade.
        """
        etapas_executadas.append(step_name)

        # Reproduzimos a falha da etapa 2 observada operacionalmente:
        # schema passa, carga MM/EWM falha e o processo deve parar ali.
        if step_name.startswith("[2/5]"):
            raise SystemExit(1)

    # main() foi carregada por runpy. Alteramos seu global run_step apenas
    # durante este teste, preservando o código produtivo e o ambiente real.
    monkeypatch.setitem(
        main.__globals__,
        "run_step",
        run_step_controlado,
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1

    # Somente as etapas 1 e 2 podem ter sido iniciadas.
    # Se 3/5, 4/5 ou 5/5 aparecerem aqui, o comportamento fail-fast
    # foi quebrado e o teste deve falhar.
    assert len(etapas_executadas) == 2
    assert etapas_executadas[0].startswith("[1/5]")
    assert etapas_executadas[1].startswith("[2/5]")
