from __future__ import annotations

import sqlite3

import pandas as pd


# ============================================================
# CONFIGURAÇÕES DO MÓDULO
# ============================================================

DEPOSITO_RESSUPRIMENTO = "1002"
TIPO_DEPOSITO_PICKING = "PT02"
FONTE_PARAMETRIZACAO = "BINMAT"


# ============================================================
# POSIÇÕES PT02 ATUAIS DA BINMAT
# ============================================================

def carregar_pt02_atuais_binmat(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    """
    Retorna as relações PT02 atualmente presentes na BINMAT.

    Importante:
    - considera somente o depósito 1002;
    - considera somente tipo de depósito PT02;
    - exige presença atual na fonte BINMAT;
    - não exclui posições de transição;
    - não filtra MIN/MAX;
    - não aplica regra de demanda.

    As regras de negócio serão aplicadas posteriormente
    pela camada rules.
    """

    sql = """
        SELECT
            p.id AS id_posicao_material,
            p.material,
            m.descricao_material,
            p.deposito,
            p.tipo_deposito,
            p.posicao,
            p.quantidade_minima,
            p.quantidade_maxima,
            p.unidade_medida,
            p.data_modificacao,
            p.momento_criacao,
            p.autor

        FROM dim_posicao_material AS p

        INNER JOIN dim_material AS m
            ON m.material = p.material

        INNER JOIN posicao_material_fontes AS f
            ON f.id_posicao_material = p.id
           AND f.fonte = ?
           AND f.presente_atual = 1

        WHERE p.deposito = ?
          AND p.tipo_deposito = ?

        ORDER BY
            p.material,
            p.posicao
    """

    df = pd.read_sql_query(
        sql,
        conn,
        params=(
            FONTE_PARAMETRIZACAO,
            DEPOSITO_RESSUPRIMENTO,
            TIPO_DEPOSITO_PICKING,
        ),
    )

    return df
