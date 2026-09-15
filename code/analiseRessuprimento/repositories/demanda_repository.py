from __future__ import annotations

from datetime import date
import sqlite3

import pandas as pd


# ============================================================
# CONFIGURAÇÕES DA REGRA DE DEMANDA
# ============================================================

MOVIMENTOS_RELEVANTES = (
    "601",
    "602",
    "Z17",
    "Z18",
)

DEBITO_CREDITO_ESPERADO = {
    "601": "H",
    "602": "S",
    "Z17": "H",
    "Z18": "S",
}


def _possui_coluna_umb(
    conn: sqlite3.Connection,
) -> bool:
    """Informa se o banco já recebeu a migration 003.

    A verificação mantém o repository compatível com bancos temporários e
    cópias antigas usados pelos testes, sem esconder a UMB quando ela existe.
    """

    colunas = conn.execute(
        "PRAGMA table_info(fact_mb51_movimentos)"
    ).fetchall()

    return any(
        coluna[1] == "unidade_medida_basica"
        for coluna in colunas
    )


# ============================================================
# DATA DE REFERÊNCIA
# ============================================================

def obter_data_referencia(
    conn: sqlite3.Connection,
) -> date:
    """
    Obtém a data máxima efetivamente carregada na MB51.

    A janela analítica é ancorada nos dados disponíveis,
    e não na data atual do computador.
    """

    resultado = conn.execute(
        """
        SELECT MAX(data_lancamento)
        FROM fact_mb51_movimentos
        """
    ).fetchone()

    if resultado is None or resultado[0] is None:
        raise ValueError(
            "A fact_mb51_movimentos não possui "
            "data_lancamento disponível."
        )

    data_referencia = pd.to_datetime(
        resultado[0],
        errors="raise",
    ).date()

    return data_referencia


# ============================================================
# PERÍODO DE ANÁLISE
# ============================================================

def calcular_data_inicio(
    data_referencia: date,
    meses: int = 6,
) -> date:
    """
    Calcula o início da janela móvel.

    Exemplo:
        referência: 2026-09-09
        início:      2026-03-09

    A janela inclui as duas datas.
    """

    if meses <= 0:
        raise ValueError(
            "A quantidade de meses deve ser maior que zero."
        )

    inicio = (
        pd.Timestamp(data_referencia)
        - pd.DateOffset(months=meses)
    )

    return inicio.date()


# ============================================================
# EXTRAÇÃO DA DEMANDA
# ============================================================

def carregar_demanda_material(
    conn: sqlite3.Connection,
    meses: int = 6,
) -> tuple[pd.DataFrame, date, date]:
    """
    Calcula a demanda líquida relevante por material.

    Regras:

        601 / H = saída comercial
        602 / S = estorno comercial
        Z17 / H = saída assistência técnica
        Z18 / S = estorno assistência técnica

    As quantidades são convertidas para magnitude positiva
    com ABS().

    Cálculos:

        demanda_comercial = qtd_601 - qtd_602

        demanda_tecnica = qtd_z17 - qtd_z18

        demanda_relevante =
            demanda_comercial + demanda_tecnica

    A função NÃO aplica ainda filtros de PT02, MIN/MAX
    ou posições de transição.
    """

    data_referencia = obter_data_referencia(conn)

    data_inicio = calcular_data_inicio(
        data_referencia,
        meses,
    )

    # A UMB pertence ao movimento cuja quantidade é somada. Uma unidade só é
    # considerada operacional quando todas as linhas relevantes do material
    # concordam. Um conflito precisa permanecer visível para análise humana.
    if _possui_coluna_umb(conn):
        selecao_umb = """
            COUNT(
                DISTINCT NULLIF(
                    TRIM(unidade_medida_basica),
                    ''
                )
            ) AS quantidade_umb_distintas,

            MIN(
                NULLIF(
                    TRIM(unidade_medida_basica),
                    ''
                )
            ) AS unidade_medida_basica,
        """
    else:
        selecao_umb = """
            0 AS quantidade_umb_distintas,
            NULL AS unidade_medida_basica,
        """

    sql = f"""
        SELECT
            material,

            {selecao_umb}

            SUM(
                CASE
                    WHEN tipo_movimento = '601'
                     AND debito_credito = 'H'
                    THEN -quantidade
                    ELSE 0
                END
            ) AS qtd_601,

            SUM(
                CASE
                    WHEN tipo_movimento = '602'
                     AND debito_credito = 'S'
                    THEN quantidade
                    ELSE 0
                END
            ) AS qtd_602,

            SUM(
                CASE
                    WHEN tipo_movimento = 'Z17'
                     AND debito_credito = 'H'
                    THEN -quantidade
                    ELSE 0
                END
            ) AS qtd_z17,

            SUM(
                CASE
                    WHEN tipo_movimento = 'Z18'
                     AND debito_credito = 'S'
                    THEN quantidade
                    ELSE 0
                END
            ) AS qtd_z18

        FROM fact_mb51_movimentos

        WHERE data_lancamento >= ?
          AND data_lancamento <= ?

          AND (
                (tipo_movimento = '601'
                 AND debito_credito = 'H')

             OR (tipo_movimento = '602'
                 AND debito_credito = 'S')

             OR (tipo_movimento = 'Z17'
                 AND debito_credito = 'H')

             OR (tipo_movimento = 'Z18'
                 AND debito_credito = 'S')
          )

        GROUP BY material
    """

    df = pd.read_sql_query(
        sql,
        conn,
        params=(
            data_inicio.isoformat(),
            data_referencia.isoformat(),
        ),
    )

    if df.empty:
        return (
            df,
            data_inicio,
            data_referencia,
        )

    colunas_quantidade = [
        "qtd_601",
        "qtd_602",
        "qtd_z17",
        "qtd_z18",
    ]

    df[colunas_quantidade] = (
        df[colunas_quantidade]
        .fillna(0.0)
        .astype(float)
    )

    df["quantidade_umb_distintas"] = pd.to_numeric(
        df["quantidade_umb_distintas"],
        errors="coerce",
    ).fillna(0).astype(int)

    # MIN() serve apenas para recuperar a unidade quando existe exatamente
    # uma opção. No conflito, descartamos esse valor para não eleger uma UMB
    # arbitrariamente.
    df.loc[
        df["quantidade_umb_distintas"] != 1,
        "unidade_medida_basica",
    ] = pd.NA

    df["status_umb"] = "UMB NÃO INFORMADA"
    df.loc[
        df["quantidade_umb_distintas"] == 1,
        "status_umb",
    ] = "UMB CONSISTENTE"
    df.loc[
        df["quantidade_umb_distintas"] > 1,
        "status_umb",
    ] = "UMB CONFLITANTE"

    df["demanda_comercial"] = (
        df["qtd_601"]
        - df["qtd_602"]
    )

    df["demanda_tecnica"] = (
        df["qtd_z17"]
        - df["qtd_z18"]
    )

    df["demanda_relevante"] = (
        df["demanda_comercial"]
        + df["demanda_tecnica"]
    )

    return (
        df,
        data_inicio,
        data_referencia,
    )
