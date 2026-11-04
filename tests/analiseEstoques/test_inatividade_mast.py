from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from analiseEstoques.scripts.streamlit_app import (
    build_excel_inatividade_mast,
    filtrar_hierarquia_inatividade_mast,
    filtrar_inatividade_mast,
    load_inatividade_mast,
)

from analiseEstoques.scripts.update_from_sap import (
    ensure_fact_mb51_mov,
    ensure_fact_snapshot,
)


def _criar_banco_inatividade(caminho: Path) -> None:
    """
    Cria um banco SQLite sintético para validar a inatividade do MAST.

    Cenários protegidos:
    - saída H com ordem vazia;
    - saída H com ordem preenchida;
    - movimento técnico 343 que não pode reiniciar a inatividade;
    - entrada recente sem saída recente;
    - material sem saída e completamente parado;
    - material com saldo zerado;
    - snapshot posterior à última MB51.
    """

    with sqlite3.connect(caminho) as connection:
        connection.executescript(
            """
            CREATE TABLE fact_estoque_snapshot (
                deposito TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                material TEXT NOT NULL,
                descricao TEXT,
                qtd_total REAL,
                val_total REAL
            );

            CREATE TABLE fact_mb51_mov (
                deposito TEXT NOT NULL,
                data_lancamento TEXT NOT NULL,
                material TEXT NOT NULL,
                deb_cred TEXT,
                ordem TEXT,
                tipo_movimento TEXT
            );

            -- Dimensão comercial mínima utilizada pela consulta de
            -- inatividade para associar BU, Diretoria e Segmento.
            CREATE TABLE dim_material (
                material TEXT PRIMARY KEY,
                bu TEXT,
                diretoria TEXT,
                segmento TEXT
            );
            """
        )

        connection.executemany(
            """
            INSERT INTO fact_estoque_snapshot (
                deposito,
                snapshot_date,
                material,
                descricao,
                qtd_total,
                val_total
            )
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            [
                # Material com entrada recente e saída antiga.
                (
                    "MAST",
                    "2026-01-02",
                    "RECENTE",
                    "Material com entrada recente",
                    1.0,
                    100.0,
                ),
                (
                    "MAST",
                    "2026-10-30",
                    "RECENTE",
                    "Material com entrada recente",
                    10.0,
                    1000.0,
                ),

                # A saída H com ordem preenchida deve ser reconhecida.
                # Como ocorreu há menos de 90 dias, o material não pode
                # aparecer entre os críticos.
                (
                    "MAST",
                    "2026-01-02",
                    "SAIDA-ORDEM",
                    "Material com saída e ordem",
                    1.0,
                    100.0,
                ),
                (
                    "MAST",
                    "2026-10-30",
                    "SAIDA-ORDEM",
                    "Material com saída e ordem",
                    2.0,
                    200.0,
                ),

                # O movimento 343 recente não pode ocultar a inatividade.
                (
                    "MAST",
                    "2026-01-02",
                    "TECNICO-343",
                    "Material com movimento técnico",
                    1.0,
                    100.0,
                ),
                (
                    "MAST",
                    "2026-10-30",
                    "TECNICO-343",
                    "Material com movimento técnico",
                    3.0,
                    300.0,
                ),

                # Material sem saída e sem movimentação recente.
                (
                    "MAST",
                    "2026-02-01",
                    "SEM-SAIDA",
                    "Material sem saída",
                    1.0,
                    100.0,
                ),
                (
                    "MAST",
                    "2026-10-30",
                    "SEM-SAIDA",
                    "Material sem saída",
                    4.0,
                    400.0,
                ),

                # Saldo zerado: não pode participar da análise.
                (
                    "MAST",
                    "2026-10-30",
                    "ZERADO",
                    "Material sem saldo",
                    0.0,
                    0.0,
                ),

                # Existe somente no snapshot posterior à MB51.
                # Como a referência comum será 30/10, ele não pode entrar.
                (
                    "MAST",
                    "2026-10-31",
                    "FUTURO",
                    "Material de snapshot futuro",
                    5.0,
                    500.0,
                ),

                # Outro depósito não pode interferir no MAST.
                (
                    "MASR",
                    "2026-10-30",
                    "OUTRO-DEPOSITO",
                    "Material de outro depósito",
                    9.0,
                    900.0,
                ),
            ],
        )

        connection.executemany(
            """
            INSERT INTO fact_mb51_mov (
                deposito,
                data_lancamento,
                material,
                deb_cred,
                ordem,
                tipo_movimento
            )
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            [
                # Saída H com ordem vazia: deve ser reconhecida.
                (
                    "MAST",
                    "2026-06-01",
                    "RECENTE",
                    "H",
                    "",
                    "201",
                ),

                # Entrada ocorrida dez dias antes da referência.
                (
                    "MAST",
                    "2026-10-20",
                    "RECENTE",
                    "S",
                    "",
                    "101",
                ),

                # Saída H com ordem preenchida: também é saída.
                (
                    "MAST",
                    "2026-09-01",
                    "SAIDA-ORDEM",
                    "H",
                    "ORDEM-1",
                    "261",
                ),

                # Última saída operacional real do material técnico.
                (
                    "MAST",
                    "2026-03-01",
                    "TECNICO-343",
                    "H",
                    "ORDEM-2",
                    "261",
                ),

                # Movimento recente de bloqueio/desbloqueio.
                # Deve ser totalmente ignorado pela inatividade.
                (
                    "MAST",
                    "2026-10-25",
                    "TECNICO-343",
                    "H",
                    "",
                    "343",
                ),

                # Única movimentação do material sem saída.
                (
                    "MAST",
                    "2026-03-01",
                    "SEM-SAIDA",
                    "S",
                    "",
                    "101",
                ),

                # Garante que a última data disponível da MB51 seja 30/10.
                # Não existe saldo para este material.
                (
                    "MAST",
                    "2026-10-30",
                    "MARCADOR-DATA",
                    "S",
                    "",
                    "101",
                ),

                # Outro depósito não pode interferir.
                (
                    "MASR",
                    "2026-10-30",
                    "OUTRO-DEPOSITO",
                    "H",
                    "",
                    "201",
                ),
            ],
        )


def test_inatividade_classifica_materiais_criticos(
    tmp_path: Path,
) -> None:
    """
    Confirma as três classificações críticas produzidas pelo cenário.
    """

    banco = tmp_path / "estoque_inatividade.sqlite"
    _criar_banco_inatividade(banco)

    resultado = load_inatividade_mast(
        str(banco),
    )

    # A ordenação segue a prioridade operacional da tela.
    assert resultado["material"].tolist() == [
        "RECENTE",
        "SEM-SAIDA",
        "TECNICO-343",
    ]

    por_material = resultado.set_index("material")

    assert (
        por_material.loc[
            "RECENTE",
            "situacao_operacional",
        ]
        == "ENTRADA RECENTE SEM SAÍDA RECENTE"
    )

    assert (
        por_material.loc[
            "SEM-SAIDA",
            "situacao_operacional",
        ]
        == "SEM SAÍDA E SEM MOVIMENTAÇÃO RECENTE"
    )

    assert (
        por_material.loc[
            "TECNICO-343",
            "situacao_operacional",
        ]
        == "ESTOQUE COMPLETAMENTE PARADO"
    )

    assert resultado["valor_atual"].sum() == pytest.approx(
        1700.0
    )

def test_inatividade_associa_hierarquia_sem_perder_materiais(
    tmp_path: Path,
) -> None:
    """
    A hierarquia comercial deve ser associada sem multiplicar o resultado.

    Materiais sem cadastro em dim_material continuam visíveis e recebem
    "SEM CLASSIFICAÇÃO" nos três níveis hierárquicos.
    """

    banco = tmp_path / "estoque_inatividade_hierarquia.sqlite"
    _criar_banco_inatividade(banco)

    with sqlite3.connect(banco) as connection:
        connection.execute(
            """
            INSERT INTO dim_material (
                material,
                bu,
                diretoria,
                segmento
            )
            VALUES (?, ?, ?, ?);
            """,
            (
                "RECENTE",
                "BU TESTE",
                "DIRETORIA TESTE",
                "SEGMENTO TESTE",
            ),
        )

    resultado = load_inatividade_mast(
        str(banco),
    )

    # A junção com a dimensão não pode criar ou remover materiais.
    assert resultado["material"].tolist() == [
        "RECENTE",
        "SEM-SAIDA",
        "TECNICO-343",
    ]

    assert len(resultado) == 3

    # O valor total deve permanecer idêntico ao resultado sem hierarquia.
    assert resultado["valor_atual"].sum() == pytest.approx(
        1700.0
    )

    por_material = resultado.set_index("material")

    assert por_material.loc["RECENTE", "bu"] == "BU TESTE"
    assert (
        por_material.loc["RECENTE", "diretoria"]
        == "DIRETORIA TESTE"
    )
    assert (
        por_material.loc["RECENTE", "segmento"]
        == "SEGMENTO TESTE"
    )

    for material_sem_classificacao in [
        "SEM-SAIDA",
        "TECNICO-343",
    ]:
        assert (
            por_material.loc[
                material_sem_classificacao,
                "bu",
            ]
            == "SEM CLASSIFICAÇÃO"
        )

        assert (
            por_material.loc[
                material_sem_classificacao,
                "diretoria",
            ]
            == "SEM CLASSIFICAÇÃO"
        )

        assert (
            por_material.loc[
                material_sem_classificacao,
                "segmento",
            ]
            == "SEM CLASSIFICAÇÃO"
        )

def test_inatividade_reconhece_todo_h_e_ignora_343_344(
    tmp_path: Path,
) -> None:
    """
    Todo movimento H operacional representa saída, com ordem vazia ou
    preenchida. Movimentos 343/344 não podem reiniciar a inatividade.
    """

    banco = tmp_path / "estoque_inatividade.sqlite"
    _criar_banco_inatividade(banco)

    resultado = load_inatividade_mast(
        str(banco),
    )

    materiais = set(
        resultado["material"].astype(str)
    )

    # H com ordem preenchida em 01/09 deixa o material com menos de
    # 90 dias sem saída; portanto, ele não é crítico.
    assert "SAIDA-ORDEM" not in materiais

    por_material = resultado.set_index("material")

    # H com ordem vazia em 01/06 é reconhecido como saída.
    assert (
        por_material.loc["RECENTE", "ultima_saida"]
        == "2026-06-01"
    )

    # O H de tipo 343 em 25/10 é ignorado. A última saída válida
    # permanece sendo a de 01/03.
    assert (
        por_material.loc["TECNICO-343", "ultima_saida"]
        == "2026-03-01"
    )

    assert (
        por_material.loc[
            "TECNICO-343",
            "ultima_movimentacao",
        ]
        == "2026-03-01"
    )


def test_inatividade_alinha_datas_e_exige_saldo_positivo(
    tmp_path: Path,
) -> None:
    """
    A referência deve ser a última data comum entre snapshots e MB51.
    Materiais sem saldo positivo nessa fotografia não participam.
    """

    banco = tmp_path / "estoque_inatividade.sqlite"
    _criar_banco_inatividade(banco)

    resultado = load_inatividade_mast(
        str(banco),
    )

    assert resultado["data_referencia"].unique().tolist() == [
        "2026-10-30"
    ]

    assert resultado["data_saldo"].unique().tolist() == [
        "2026-10-30"
    ]

    materiais = set(
        resultado["material"].astype(str)
    )

    assert "ZERADO" not in materiais
    assert "FUTURO" not in materiais
    assert "OUTRO-DEPOSITO" not in materiais


def test_funcoes_de_schema_criam_indices_de_inatividade(
    tmp_path: Path,
) -> None:
    """
    Bancos novos devem receber automaticamente os índices usados pela
    consulta de inatividade.
    """

    banco = tmp_path / "estoque_indices.sqlite"

    with sqlite3.connect(banco) as connection:
        ensure_fact_snapshot(connection)
        ensure_fact_mb51_mov(connection)

        indices = {
            linha[0]
            for linha in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name IN (
                      'idx_snapshot_inatividade_mast',
                      'idx_mb51_inatividade_mast'
                  );
                """
            ).fetchall()
        }

        assert indices == {
            "idx_snapshot_inatividade_mast",
            "idx_mb51_inatividade_mast",
        }

        colunas_snapshot = [
            linha[2]
            for linha in connection.execute(
                """
                PRAGMA index_info(
                    'idx_snapshot_inatividade_mast'
                );
                """
            ).fetchall()
        ]

        assert colunas_snapshot == [
            "material",
            "snapshot_date",
            "qtd_total",
            "val_total",
        ]

        colunas_mb51 = [
            linha[2]
            for linha in connection.execute(
                """
                PRAGMA index_info(
                    'idx_mb51_inatividade_mast'
                );
                """
            ).fetchall()
        ]

        assert colunas_mb51 == [
            "material",
            "data_lancamento",
            "deb_cred",
            "ordem",
        ]

        sql_indice_mb51 = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_mb51_inatividade_mast';
            """
        ).fetchone()[0]

        assert "343" in sql_indice_mb51
        assert "344" in sql_indice_mb51

def test_excel_inatividade_documenta_janelas_temporais(
    tmp_path: Path,
) -> None:
    """
    O Excel deve preservar todos os materiais do recorte e documentar
    corretamente as duas janelas temporais utilizadas pela análise:

    - 30 dias para identificar uma entrada recente;
    - 90 dias para caracterizar ausência recente de saída ou movimentação.

    Este teste impede que a documentação exportada fique diferente da
    regra aplicada pela consulta SQL.
    """

    banco = tmp_path / "estoque_excel_inatividade.sqlite"
    _criar_banco_inatividade(banco)

    resultado = load_inatividade_mast(
        str(banco),
    )

    conteudo_excel = build_excel_inatividade_mast(
        resultado,
    )

    assert isinstance(conteudo_excel, bytes)
    assert conteudo_excel

        # ------------------------------------------------------------
    # Valida a estrutura e a formatação da aba de detalhes.
    # ------------------------------------------------------------
    # Esta verificação protege contra deslocamentos das formatações
    # quando novas colunas são incluídas antes dos dados operacionais.
    workbook = load_workbook(
        BytesIO(conteudo_excel),
        data_only=False,
    )

    worksheet = workbook["INATIVIDADE"]

    assert worksheet.max_column == 18

    # Quantidade e valor.
    assert worksheet["F2"].number_format == "#,##0"
    assert worksheet["G2"].number_format == "R$ #,##0.00"

    # Datas.
    for coluna_data in ["H", "I", "K", "M"]:
        assert (
            worksheet[f"{coluna_data}2"].number_format
            == "dd/mm/yyyy"
        )

    # Dias e quantidades de registros.
    for coluna_inteira in ["J", "L", "N", "O", "P"]:
        assert (
            worksheet[f"{coluna_inteira}2"].number_format
            == "#,##0"
        )

    with pd.ExcelFile(BytesIO(conteudo_excel)) as arquivo_excel:
        assert arquivo_excel.sheet_names == [
            "INATIVIDADE",
            "PARAMETROS",
        ]

        detalhe = pd.read_excel(
            arquivo_excel,
            sheet_name="INATIVIDADE",
        )

        parametros_df = pd.read_excel(
            arquivo_excel,
            sheet_name="PARAMETROS",
        )

    # O Excel contém todos os materiais do recorte. O Top 20 e o Top 50
    # pertencem somente à apresentação visual do Streamlit.
    assert len(detalhe) == len(resultado)

        # A aba detalhada deve identificar a hierarquia comercial do material.
    assert detalhe.columns[:5].tolist() == [
        "Material",
        "Descrição",
        "BU",
        "Diretoria",
        "Segmento",
    ]

    # O banco sintético não possui classificação para esses materiais.
    # Mesmo assim, eles devem permanecer no Excel de forma auditável.
    assert set(detalhe["BU"]) == {
        "SEM CLASSIFICAÇÃO",
    }

    assert set(detalhe["Diretoria"]) == {
        "SEM CLASSIFICAÇÃO",
    }

    assert set(detalhe["Segmento"]) == {
        "SEM CLASSIFICAÇÃO",
    }

    parametros = dict(
        zip(
            parametros_df["Parâmetro"],
            parametros_df["Valor"],
        )
    )

    assert "30 dias" in str(
        parametros["Janela de entrada recente"]
    )

    assert "até 30 dias" in str(
        parametros["Entrada recente"]
    )

    assert "mais de 90 dias" in str(
        parametros["Sem saída recente"]
    )

    assert "90 dias" in str(
        parametros["Sem movimentação recente"]
    )

    assert int(parametros["Materiais exportados"]) == len(
        resultado
    )

def test_filtro_inatividade_sem_situacao_representa_todas() -> None:
    """
    A seleção vazia de situações representa "Todas as situações".

    Este teste protege a pesquisa por material contra a regressão em que
    o DataFrame era esvaziado antes da aplicação do código ou descrição.
    """

    dados = pd.DataFrame(
        [
            {
                "material": "4301126",
                "descricao": (
                    "INVERSOR EX MONO 220V/60HZ G IN010KEXG"
                ),
                "valor_atual": 9242.74,
                "situacao_operacional": (
                    "SEM SAÍDA E SEM MOVIMENTAÇÃO RECENTE"
                ),
                "prioridade": 1,
                "dias_sem_saida": 122,
            },
            {
                "material": "4822015",
                "descricao": "NOBREAK TESTE",
                "valor_atual": 1000.00,
                "situacao_operacional": (
                    "ENTRADA RECENTE SEM SAÍDA RECENTE"
                ),
                "prioridade": 2,
                "dias_sem_saida": 100,
            },
        ]
    )

    # Sem situações selecionadas, todos os materiais permanecem no recorte.
    resultado_todas = filtrar_inatividade_mast(
        df_inatividade=dados,
        situacoes_selecionadas=[],
        filtro_material="",
        valor_minimo=0.0,
        somente_entrada_recente=False,
    )

    assert set(resultado_todas["material"]) == {
        "4301126",
        "4822015",
    }

    # A pesquisa é aplicada sobre o conjunto completo representado por
    # "Todas as situações".
    resultado_pesquisa = filtrar_inatividade_mast(
        df_inatividade=dados,
        situacoes_selecionadas=[],
        filtro_material="4301126",
        valor_minimo=0.0,
        somente_entrada_recente=False,
    )

    assert resultado_pesquisa["material"].tolist() == [
        "4301126",
    ]

    assert resultado_pesquisa.iloc[0]["situacao_operacional"] == (
        "SEM SAÍDA E SEM MOVIMENTAÇÃO RECENTE"
    )

def test_filtro_hierarquico_inatividade_respeita_encadeamento() -> None:
    """
    BU, Diretoria e Segmento devem restringir progressivamente o recorte.

    A ausência de seleção preserva todos os materiais.
    """

    dados = pd.DataFrame(
        [
            {
                "material": "ITEM-1",
                "bu": "BU A",
                "diretoria": "DIRETORIA 1",
                "segmento": "SEGMENTO X",
            },
            {
                "material": "ITEM-2",
                "bu": "BU A",
                "diretoria": "DIRETORIA 2",
                "segmento": "SEGMENTO Y",
            },
            {
                "material": "ITEM-3",
                "bu": "BU B",
                "diretoria": "DIRETORIA 3",
                "segmento": "SEGMENTO Z",
            },
        ]
    )

    resultado_completo = filtrar_hierarquia_inatividade_mast(
        df_inatividade=dados,
        filtro_bu="Todas",
        filtro_diretoria="Todas",
        filtro_segmento="Todos",
    )

    assert resultado_completo["material"].tolist() == [
        "ITEM-1",
        "ITEM-2",
        "ITEM-3",
    ]

    resultado_bu = filtrar_hierarquia_inatividade_mast(
        df_inatividade=dados,
        filtro_bu="BU A",
        filtro_diretoria="Todas",
        filtro_segmento="Todos",
    )

    assert resultado_bu["material"].tolist() == [
        "ITEM-1",
        "ITEM-2",
    ]

    resultado_diretoria = filtrar_hierarquia_inatividade_mast(
        df_inatividade=dados,
        filtro_bu="BU A",
        filtro_diretoria="DIRETORIA 2",
        filtro_segmento="Todos",
    )

    assert resultado_diretoria["material"].tolist() == [
        "ITEM-2",
    ]

    resultado_segmento = filtrar_hierarquia_inatividade_mast(
        df_inatividade=dados,
        filtro_bu="BU A",
        filtro_diretoria="DIRETORIA 1",
        filtro_segmento="SEGMENTO X",
    )

    assert resultado_segmento["material"].tolist() == [
        "ITEM-1",
    ]