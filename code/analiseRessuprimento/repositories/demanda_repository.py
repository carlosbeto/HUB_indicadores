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

    sql = """
        SELECT
            material,

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
