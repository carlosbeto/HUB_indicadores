from __future__ import annotations

import sqlite3

import pandas as pd

from repositories.demanda_repository import carregar_demanda_material
from repositories.posicao_repository import carregar_pt02_atuais_binmat


# ============================================================
# CONFIGURAÇÕES DA REGRA
# ============================================================

POSICOES_TRANSICAO = {
    "PT02-001-002-001",
    "PT02-003-053-001",
}


# ============================================================
# UNIVERSO PARA PARAMETRIZAÇÃO
# ============================================================

def calcular_prioridade_parametrizacao_pt02(
    conn: sqlite3.Connection,
    meses: int = 6,
) -> tuple[pd.DataFrame, dict]:
    """
    Calcula a prioridade de parametrização das posições PT02.

    Universo:
    - PT02 atualmente presente na BINMAT;
    - exclui posições de transição;
    - quantidade mínima = 0;
    - quantidade máxima = 0;
    - demanda líquida relevante > 0.

    Prioridade:
    - exclusivamente pela demanda líquida relevante;
    - maior demanda = maior prioridade.

    Retorna:
    - DataFrame com o ranking;
    - dicionário com indicadores de auditoria da regra.
    """

    # --------------------------------------------------------
    # 1. Carregar fontes homologadas
    # --------------------------------------------------------

    df_posicoes = carregar_pt02_atuais_binmat(conn)

    (
        df_demanda,
        data_inicio,
        data_referencia,
    ) = carregar_demanda_material(
        conn,
        meses=meses,
    )

    # --------------------------------------------------------
    # 2. Excluir posições de transição
    # --------------------------------------------------------

    df_definitivas = df_posicoes[
        ~df_posicoes["posicao"].isin(POSICOES_TRANSICAO)
    ].copy()

    # --------------------------------------------------------
    # 3. Selecionar PT02 sem parametrização MIN/MAX
    # --------------------------------------------------------

    df_sem_parametrizacao = df_definitivas[
        (df_definitivas["quantidade_minima"] == 0)
        & (df_definitivas["quantidade_maxima"] == 0)
    ].copy()

    # --------------------------------------------------------
    # 4. Cruzar posição com demanda
    # --------------------------------------------------------

    df_resultado = df_sem_parametrizacao.merge(
        df_demanda,
        on="material",
        how="left",
        validate="one_to_one",
    )

    # Materiais sem movimento relevante na janela recebem zero.
    colunas_demanda = [
        "qtd_601",
        "qtd_602",
        "qtd_z17",
        "qtd_z18",
        "demanda_comercial",
        "demanda_tecnica",
        "demanda_relevante",
    ]

    df_resultado[colunas_demanda] = (
        df_resultado[colunas_demanda]
        .fillna(0.0)
    )

    # --------------------------------------------------------
    # 5. Manter somente demanda líquida positiva
    # --------------------------------------------------------

    df_resultado = df_resultado[
        df_resultado["demanda_relevante"] > 0
    ].copy()

    # --------------------------------------------------------
    # 6. Ranking
    # --------------------------------------------------------

    df_resultado = df_resultado.sort_values(
        by=[
            "demanda_relevante",
            "material",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(drop=True)

    df_resultado.insert(
        0,
        "prioridade",
        range(1, len(df_resultado) + 1),
    )

    # --------------------------------------------------------
    # 7. Organizar saída
    # --------------------------------------------------------

    colunas_saida = [
        "prioridade",
        "material",
        "descricao_material",
        "posicao",
        "quantidade_minima",
        "quantidade_maxima",
        "unidade_medida",
        "qtd_601",
        "qtd_602",
        "qtd_z17",
        "qtd_z18",
        "demanda_comercial",
        "demanda_tecnica",
        "demanda_relevante",
    ]

    df_resultado = df_resultado[colunas_saida]

    # --------------------------------------------------------
    # 8. Indicadores para auditoria
    # --------------------------------------------------------

    indicadores = {
        "data_inicio": data_inicio,
        "data_referencia": data_referencia,
        "meses": meses,
        "pt02_binmat": len(df_posicoes),
        "pt02_transicao": int(
            df_posicoes["posicao"]
            .isin(POSICOES_TRANSICAO)
            .sum()
        ),
        "pt02_definitivas": len(df_definitivas),
        "pt02_sem_parametrizacao": len(
            df_sem_parametrizacao
        ),
        "pt02_priorizadas": len(df_resultado),
    }

    return df_resultado, indicadores
