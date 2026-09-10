from __future__ import annotations

import sqlite3

import pandas as pd


# ============================================================
# CONFIGURAÇÕES
# ============================================================

DEPOSITO_RESSUPRIMENTO = "1002"

TIPO_DEPOSITO_PICKING = "PT02"
TIPO_DEPOSITO_ORIGEM = "T001"

TIPO_ESTOQUE_LIVRE = "F5"
TIPO_ESTOQUE_BLOQUEADO = "B5"

FONTE_ESTOQUE = "VISAO_GERAL"
FONTE_PARAMETRIZACAO = "BINMAT"


# ============================================================
# SALDO ATUAL PT02
# ============================================================

def carregar_saldo_pt02_atual(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    """
    Retorna o saldo atual das posições PT02 presentes
    na VISAO_GERAL.

    Mantém F5 e B5 separados.

    Não transforma ausência de F5 em saldo zero.
    Não aplica MIN/MAX.
    Não aplica regra de ressuprimento.
    """

    sql = """
        SELECT
            p.id AS id_posicao_material,
            p.material,
            p.posicao,
            s.tipo_estoque,
            s.denominacao_tipo_estoque,
            s.quantidade,
            s.quantidade_entrada,
            s.quantidade_saida,
            s.quantidade_disponivel,
            s.unidade_medida,
            s.arquivo_origem

        FROM dim_posicao_material AS p

        INNER JOIN posicao_material_fontes AS f
            ON f.id_posicao_material = p.id
           AND f.fonte = ?
           AND f.presente_atual = 1

        INNER JOIN fact_saldo_posicao AS s
            ON s.id_posicao_material = p.id

        WHERE p.deposito = ?
          AND p.tipo_deposito = ?
          AND s.tipo_estoque IN (?, ?)

        ORDER BY
            p.material,
            p.posicao,
            s.tipo_estoque
    """

    return pd.read_sql_query(
        sql,
        conn,
        params=(
            FONTE_ESTOQUE,
            DEPOSITO_RESSUPRIMENTO,
            TIPO_DEPOSITO_PICKING,
            TIPO_ESTOQUE_LIVRE,
            TIPO_ESTOQUE_BLOQUEADO,
        ),
    )


# ============================================================
# SALDO ATUAL T001 AGREGADO POR MATERIAL
# ============================================================

def carregar_saldo_t001_por_material(
    conn: sqlite3.Connection,
) -> pd.DataFrame:
    """
    Consolida os saldos atuais das posições T001 por material.

    Regras:
    - considera posições T001 presentes atualmente na
      VISAO_GERAL;
    - soma todas as T001 do material;
    - F5 e B5 permanecem separados;
    - informa quantas posições T001 participam;
    - informa quantas relações atuais também estão
      parametrizadas na BINMAT.

    A ausência de parametrização BINMAT não elimina a T001
    da análise de estoque.
    """

    sql = """
        SELECT
            p.material,

            COUNT(
                DISTINCT p.posicao
            ) AS qtd_posicoes_t001,

            COUNT(
                DISTINCT CASE
                    WHEN fb.id IS NOT NULL
                    THEN p.posicao
                END
            ) AS qtd_posicoes_t001_binmat,

            SUM(
                CASE
                    WHEN s.tipo_estoque = ?
                    THEN COALESCE(s.quantidade_disponivel, 0)
                    ELSE 0
                END
            ) AS saldo_t001_f5,

            SUM(
                CASE
                    WHEN s.tipo_estoque = ?
                    THEN COALESCE(s.quantidade_disponivel, 0)
                    ELSE 0
                END
            ) AS saldo_t001_b5

        FROM dim_posicao_material AS p

        INNER JOIN posicao_material_fontes AS fv
            ON fv.id_posicao_material = p.id
           AND fv.fonte = ?
           AND fv.presente_atual = 1

        INNER JOIN fact_saldo_posicao AS s
            ON s.id_posicao_material = p.id
           AND s.tipo_estoque IN (?, ?)

        LEFT JOIN posicao_material_fontes AS fb
            ON fb.id_posicao_material = p.id
           AND fb.fonte = ?
           AND fb.presente_atual = 1

        WHERE p.deposito = ?
          AND p.tipo_deposito = ?

        GROUP BY
            p.material

        ORDER BY
            p.material
    """

    return pd.read_sql_query(
        sql,
        conn,
        params=(
            TIPO_ESTOQUE_LIVRE,
            TIPO_ESTOQUE_BLOQUEADO,
            FONTE_ESTOQUE,
            TIPO_ESTOQUE_LIVRE,
            TIPO_ESTOQUE_BLOQUEADO,
            FONTE_PARAMETRIZACAO,
            DEPOSITO_RESSUPRIMENTO,
            TIPO_DEPOSITO_ORIGEM,
        ),
    )
