from __future__ import annotations

import os
import runpy
from pathlib import Path

import pandas as pd
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
build_rows = LOADER["build_rows"]
main = LOADER["main"]

# O baseline mensal possui um loader próprio. Carregamos sua função de
# transformação separadamente para testar as regras que protegem a
# granularidade snapshot + depósito + material antes da gravação no SQLite.
BASELINE_LOADER_PATH = (
    Path(__file__).resolve().parents[2]
    / "code"
    / "analiseInventarios"
    / "scripts"
    / "load_baseline_snapshot.py"
)

BASELINE_LOADER = runpy.run_path(str(BASELINE_LOADER_PATH))

transform_baseline_df = BASELINE_LOADER["transform_baseline_df"]

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


def test_main_falha_quando_fonte_obrigatoria_esta_ausente(
    tmp_path,
    monkeypatch,
    capsys,
):
    """
    A ausência de uma fonte obrigatória deve ser tratada como falha real
    do processo, e não apenas como uma mensagem de erro no terminal.

    Esse contrato é importante porque o orquestrador usa o código de saída
    do loader para decidir se pode executar as próximas etapas do ETL.
    """

    mm_dir = tmp_path / "MM_IN"
    ewm_dir = tmp_path / "EWM_IN"

    mm_dir.mkdir()
    ewm_dir.mkdir()

    # Criamos somente a fonte MM. A ausência proposital do arquivo EWM
    # reproduz, de forma isolada, a falha observada na PROD sem alterar
    # nenhum arquivo ou banco real do projeto.
    arquivo_mm = mm_dir / "mm_teste.xlsx"
    arquivo_mm.touch()

    db_path = tmp_path / "data_db" / "inventarios.sqlite"

    # A função main() foi carregada por runpy. Alterando seus globals para
    # caminhos temporários, executamos a lógica produtiva em um ambiente
    # completamente isolado das pastas DEV e PROD.
    monkeypatch.setitem(main.__globals__, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(main.__globals__, "MM_DIR", mm_dir)
    monkeypatch.setitem(main.__globals__, "EWM_DIR", ewm_dir)
    monkeypatch.setitem(main.__globals__, "DB_PATH", db_path)

    with pytest.raises(SystemExit) as exc_info:
        main()

    # Código diferente de zero comunica ao orquestrador que esta etapa
    # falhou e que o ETL não deve continuar para as etapas seguintes.
    assert exc_info.value.code == 1

    saida = capsys.readouterr().out

    assert "[ERRO] ETL de Inventários interrompido." in saida
    assert "EWM" in saida
    assert "[ERRO] Banco não foi alterado." in saida

    # Como a falha acontece antes da fase de persistência, nem mesmo o
    # arquivo SQLite deve ser criado neste cenário.
    assert not db_path.exists()

def test_build_rows_ewm_preserva_metodo_inventario():
    """
    O método de inventário físico do EWM deve ser persistido usando
    o código original do SAP, normalizado para maiúsculas.
    """

    df = pd.DataFrame(
        [
            {
                "DocInvFísico": "1001",
                "Item": "1",
                "Produto": "1234567",
                "Tipo de depósito": "PT02",
                "Data de lançamento": "28/08/2026",
                "Qtd.registrada": 10,
                "Qtd.cont.inv.": 10,
                "Quantidade de diferença": 0,
                "Valor de diferença": 0,
                "Status do inventário físico": "CONTADO",
                "Contador": "TESTE",
                "Área armazmto.": "AREA1",
                "Posição no depósito": "POS1",
                "Tipo de estoque": "F2",
                "Ordem de depósito": "OT1",
                "Método de inventário físico": "hl",
            }
        ]
    )

    rows = build_rows(
        df,
        source_system="EWM",
        file_name="ewm_teste.xlsx",
        loaded_at="2026-08-28T14:00:00",
    )

    assert len(rows) == 1
    assert rows[0]["count_method"] == "HL"


def test_build_rows_mm_mantem_metodo_inventario_nulo():
    """
    MM não possui atualmente um método equivalente ao HS/HL do EWM.
    O atributo deve permanecer NULL, sem classificação presumida.
    """

    df = pd.DataFrame(
        [
            {
                "Documento inventário": "2001",
                "Item": "1",
                "Material": "1234567",
                "Depósito": "MAST",
                "Data contagem": "28/08/2026",
                "Qtd.registrada": 10,
                "Qtd.contada": 10,
                "Qtd.diferença": 0,
                "Status invent.físico": "CONTADO",
                "Contado por": "TESTE",
                "Tipo de estoque": "L",
            }
        ]
    )

    rows = build_rows(
        df,
        source_system="MM",
        file_name="mm_teste.xlsx",
        loaded_at="2026-08-28T14:00:00",
    )

    assert len(rows) == 1
    assert rows[0]["count_method"] is None


def test_baseline_remove_duplicata_integralmente_identica():
    """
    Uma repetição integralmente idêntica da fonte SAP não representa
    um novo saldo e não deve derrubar o ETL por violação da chave única.

    O loader deve preservar apenas uma ocorrência antes da persistência.
    """

    df = pd.DataFrame(
        [
            {
                "Material": "1151665",
                "Descrição de material": "SACO PROT PC 305X150MM",
                "Depósito": "WEPV",
                "Estoque de utilização livre": 100,
                "Estoque em controle de qualidade": 0,
                "Estoque bloqueado": 0,
                "Valor do estoque de utilização livre": 35,
                "Valor do estoque no controle de qualidade": 0,
                "Valor do estoque bloqueado": 0,
            },
            {
                "Material": "1151665",
                "Descrição de material": "SACO PROT PC 305X150MM",
                "Depósito": "WEPV",
                "Estoque de utilização livre": 100,
                "Estoque em controle de qualidade": 0,
                "Estoque bloqueado": 0,
                "Valor do estoque de utilização livre": 35,
                "Valor do estoque no controle de qualidade": 0,
                "Valor do estoque bloqueado": 0,
            },
        ]
    )

    # A data do snapshot é obtida pelo loader a partir do nome do arquivo.
    file_path = Path("Materiais01092026.xlsx")

    resultado = transform_baseline_df(df, file_path)

    assert len(resultado) == 1
    assert resultado.iloc[0]["warehouse_code"] == "WEPV"
    assert resultado.iloc[0]["material"] == "1151665"
    assert resultado.iloc[0]["qty_total"] == 100


def test_baseline_nao_remove_mesma_chave_com_saldos_diferentes():
    """
    Registros com a mesma chave lógica, mas saldos diferentes, representam
    uma ambiguidade real da fonte e não podem ser descartados automaticamente.

    Mantê-los permite que a validação de unicidade do banco continue
    protegendo o baseline contra consolidações ou sobrescritas indevidas.
    """

    df = pd.DataFrame(
        [
            {
                "Material": "1151665",
                "Descrição de material": "SACO PROT PC 305X150MM",
                "Depósito": "WEPV",
                "Estoque de utilização livre": 100,
                "Estoque em controle de qualidade": 0,
                "Estoque bloqueado": 0,
                "Valor do estoque de utilização livre": 35,
                "Valor do estoque no controle de qualidade": 0,
                "Valor do estoque bloqueado": 0,
            },
            {
                "Material": "1151665",
                "Descrição de material": "SACO PROT PC 305X150MM",
                "Depósito": "WEPV",
                "Estoque de utilização livre": 120,
                "Estoque em controle de qualidade": 0,
                "Estoque bloqueado": 0,
                "Valor do estoque de utilização livre": 42,
                "Valor do estoque no controle de qualidade": 0,
                "Valor do estoque bloqueado": 0,
            },
        ]
    )

    file_path = Path("Materiais01092026.xlsx")

    resultado = transform_baseline_df(df, file_path)

    # As duas linhas devem permanecer. O loader não pode escolher,
    # somar ou sobrescrever silenciosamente uma delas.
    assert len(resultado) == 2

    assert resultado["qty_total"].tolist() == [100, 120]

    # Ambas continuam representando a mesma chave lógica do banco,
    # evidenciando que existe uma inconsistência que requer tratamento.
    assert (
        resultado[
            ["snapshot_date", "warehouse_code", "material"]
        ]
        .drop_duplicates()
        .shape[0]
        == 1
    )
