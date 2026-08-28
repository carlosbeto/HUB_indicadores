from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest


# O arquivo produtivo começa por "01_", portanto não pode ser importado
# normalmente como um módulo Python.
#
# runpy permite carregar suas funções sem executar main(), já que o script
# recebe um __name__ diferente de "__main__".
LOADER_PATH = (
    Path(__file__).resolve().parents[2]
    / "code"
    / "analiseInventarios"
    / "scripts"
    / "01_load_excels.py"
)

LOADER = runpy.run_path(str(LOADER_PATH))

list_xlsx = LOADER["list_xlsx"]
choose_latest_xlsx = LOADER["choose_latest_xlsx"]
find_missing_sources = LOADER["find_missing_sources"]


def test_choose_latest_xlsx_usa_mtime_e_nao_nome(tmp_path):
    """
    O arquivo fisicamente mais recente deve vencer independentemente
    da ordem alfabética ou do nome fornecido pelo SAP/usuário.
    """

    arquivo_nome_maior = tmp_path / "ZZZ_relatorio_antigo.xlsx"
    arquivo_nome_menor = tmp_path / "AAA_relatorio_novo.xlsx"

    arquivo_nome_maior.touch()
    arquivo_nome_menor.touch()

    # Datas artificiais e determinísticas:
    # ZZZ é mais antigo; AAA é fisicamente mais recente.
    os.utime(arquivo_nome_maior, (1000, 1000))
    os.utime(arquivo_nome_menor, (2000, 2000))

    escolhido = choose_latest_xlsx(tmp_path)

    assert escolhido == arquivo_nome_menor


def test_list_xlsx_ignora_arquivo_temporario_do_excel(tmp_path):
    """
    Arquivos temporários criados pelo Excel (~$...) não podem ser
    considerados fontes válidas para o ETL.
    """

    temporario = tmp_path / "~$relatorio.xlsx"
    temporario.touch()

    assert list_xlsx(tmp_path) == []
    assert choose_latest_xlsx(tmp_path) is None


@pytest.mark.parametrize(
    ("mm_presente", "ewm_presente", "esperado"),
    [
        (True, True, []),
        (False, True, ["MM"]),
        (True, False, ["EWM"]),
        (False, False, ["MM", "EWM"]),
    ],
)
def test_find_missing_sources_exige_mm_e_ewm(
    tmp_path,
    mm_presente,
    ewm_presente,
    esperado,
):
    """
    O ETL completo só pode prosseguir quando MM e EWM possuem
    arquivos válidos selecionados.
    """

    arquivo_mm = tmp_path / "mm.xlsx" if mm_presente else None
    arquivo_ewm = tmp_path / "ewm.xlsx" if ewm_presente else None

    selected_files = {
        "MM": arquivo_mm,
        "EWM": arquivo_ewm,
    }

    assert find_missing_sources(selected_files) == esperado
