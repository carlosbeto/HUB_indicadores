from __future__ import annotations

import sqlite3

import pandas as pd

from repositories.estoque_repository import (
    carregar_saldo_pt02_atual,
    carregar_saldo_t001_por_material,
)


# ============================================================
# CONSOLIDAÇÃO DO SALDO PT02
# ============================================================

def _consolidar_saldo_pt02(
    df_saldo_pt02: pd.DataFrame,
) -> pd.DataFrame:
    """
    Consolida o saldo atual da PT02 para uma linha por
    material + posição.

    Regras:
    - F5 e B5 permanecem em colunas separadas;
    - quantidade utilizada = quantidade_disponivel;
    - posição encontrada apenas com B5 continua sendo uma
      posição identificada;
    - nesse caso, F5 recebe zero;
    - ausência completa da posição na VISAO_GERAL não é
      transformada em zero nesta etapa.
    """

    colunas_saida = [
        "material",
        "posicao",
        "saldo_pt02_f5",
        "saldo_pt02_b5",
        "saldo_pt02_identificado",
    ]

    if df_saldo_pt02.empty:
        return pd.DataFrame(
            columns=colunas_saida
        )

    colunas_obrigatorias = {
        "material",
        "posicao",
        "tipo_estoque",
        "quantidade_disponivel",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(df_saldo_pt02.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "O saldo PT02 não possui as colunas obrigatórias: "
            + ", ".join(sorted(colunas_ausentes))
        )

    df = df_saldo_pt02.copy()

    df["quantidade_disponivel"] = pd.to_numeric(
        df["quantidade_disponivel"],
        errors="coerce",
    ).fillna(0.0)

    df["saldo_pt02_f5"] = df["quantidade_disponivel"].where(
        df["tipo_estoque"] == "F5",
        0.0,
    )

    df["saldo_pt02_b5"] = df["quantidade_disponivel"].where(
        df["tipo_estoque"] == "B5",
        0.0,
    )

    df_consolidado = (
        df.groupby(
            [
                "material",
                "posicao",
            ],
            as_index=False,
        )
        .agg(
            saldo_pt02_f5=(
                "saldo_pt02_f5",
                "sum",
            ),
            saldo_pt02_b5=(
                "saldo_pt02_b5",
                "sum",
            ),
        )
    )

    df_consolidado["saldo_pt02_identificado"] = True

    return df_consolidado[
        colunas_saida
    ]


# ============================================================
# SITUAÇÃO FÍSICA
# ============================================================

def _classificar_situacao_fisica(
    linha: pd.Series,
) -> str:
    """
    Classifica o contexto físico do material no momento
    da formação da onda.

    A classificação é descritiva.
    Ela NÃO altera a prioridade de demanda.
    """

    pt02_identificado = bool(
        linha["saldo_pt02_identificado"]
    )

    saldo_pt02_f5 = float(
        linha["saldo_pt02_f5"]
    )

    saldo_t001_f5 = float(
        linha["saldo_t001_f5"]
    )

    if not pt02_identificado:
        if saldo_t001_f5 > 0:
            return (
                "PT02 NÃO IDENTIFICADO + "
                "T001 COM F5"
            )

        return (
            "PT02 NÃO IDENTIFICADO + "
            "SEM T001 F5"
        )

    if saldo_pt02_f5 > 0:
        if saldo_t001_f5 > 0:
            return (
                "PT02 COM F5 + "
                "T001 COM F5"
            )

        return (
            "PT02 COM F5 + "
            "SEM T001 F5"
        )

    if saldo_t001_f5 > 0:
        return (
            "PT02 F5 ZERO + "
            "T001 COM F5"
        )

    return (
        "PT02 F5 ZERO + "
        "SEM T001 F5"
    )


# ============================================================
# SNAPSHOT FÍSICO DA ONDA
# ============================================================

def compor_snapshot_fisico_onda(
    conn: sqlite3.Connection,
    df_onda: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    Acrescenta o contexto físico atual à onda de
    parametrização.

    A função:
    - recebe uma onda já formada pela regra de demanda;
    - consolida PT02 F5/B5 por material + posição;
    - agrega T001 já consolidada pelo repository;
    - preserva a ordem de prioridade recebida;
    - não grava informações no banco;
    - não altera a prioridade da onda.
    """

    if df_onda is None:
        raise ValueError(
            "A onda de parametrização não foi informada."
        )

    if df_onda.empty:
        raise ValueError(
            "A onda de parametrização está vazia."
        )

    colunas_obrigatorias = {
        "prioridade",
        "material",
        "posicao",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(df_onda.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "A onda não possui as colunas obrigatórias: "
            + ", ".join(sorted(colunas_ausentes))
        )

    if df_onda.duplicated(
        subset=[
            "material",
            "posicao",
        ]
    ).any():
        raise ValueError(
            "A onda possui material + posição PT02 duplicados."
        )

    # --------------------------------------------------------
    # 1. Carregar estoques atuais
    # --------------------------------------------------------

    df_pt02_bruto = carregar_saldo_pt02_atual(
        conn
    )

    df_t001 = carregar_saldo_t001_por_material(
        conn
    )

    # --------------------------------------------------------
    # 2. Consolidar PT02
    # --------------------------------------------------------

    df_pt02 = _consolidar_saldo_pt02(
        df_pt02_bruto
    )

    # --------------------------------------------------------
    # 3. Cruzar onda com PT02
    # --------------------------------------------------------

    df_snapshot = df_onda.merge(
        df_pt02,
        on=[
            "material",
            "posicao",
        ],
        how="left",
        validate="one_to_one",
    )

    # --------------------------------------------------------
    # 4. Cruzar onda com T001
    # --------------------------------------------------------

    # Ausência completa de linha PT02 deve permanecer
    # distinguível de uma posição identificada com F5 = 0.
    df_snapshot["saldo_pt02_identificado"] = (
        df_snapshot["saldo_pt02_identificado"]
        .eq(True)
        .astype(bool)
    )

    # Normalizar explicitamente os saldos PT02 como numéricos.
    for coluna in [
        "saldo_pt02_f5",
        "saldo_pt02_b5",
    ]:
        df_snapshot[coluna] = pd.to_numeric(
            df_snapshot[coluna],
            errors="coerce",
        )

    mascara_pt02_identificada = (
        df_snapshot["saldo_pt02_identificado"]
    )

    # Se a posição PT02 foi identificada, a ausência de F5
    # ou B5 significa saldo zero para aquele tipo de estoque.
    # Se a posição não foi identificada, o NaN é preservado.
    df_snapshot.loc[
        mascara_pt02_identificada,
        [
            "saldo_pt02_f5",
            "saldo_pt02_b5",
        ],
    ] = (
        df_snapshot.loc[
            mascara_pt02_identificada,
            [
                "saldo_pt02_f5",
                "saldo_pt02_b5",
            ],
        ]
        .fillna(0.0)
    )

    df_snapshot = df_snapshot.merge(
        df_t001,
        on="material",
        how="left",
        validate="one_to_one",
    )

    colunas_t001_quantidade = [
        "saldo_t001_f5",
        "saldo_t001_b5",
    ]

    colunas_t001_contagem = [
        "qtd_posicoes_t001",
        "qtd_posicoes_t001_binmat",
    ]

    for coluna in colunas_t001_quantidade:
        df_snapshot[coluna] = pd.to_numeric(
            df_snapshot[coluna],
            errors="coerce",
        ).fillna(0.0)

    for coluna in colunas_t001_contagem:
        df_snapshot[coluna] = (
            pd.to_numeric(
                df_snapshot[coluna],
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    # --------------------------------------------------------
    # 5. Classificar contexto físico
    # --------------------------------------------------------

    df_snapshot["situacao_fisica"] = (
        df_snapshot.apply(
            _classificar_situacao_fisica,
            axis=1,
        )
    )

    # --------------------------------------------------------
    # 6. Preservar prioridade oficial
    # --------------------------------------------------------

    df_snapshot = df_snapshot.sort_values(
        by="prioridade",
        ascending=True,
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # 7. Indicadores de auditoria
    # --------------------------------------------------------

    indicadores = {
        "qtd_materiais": int(
            len(df_snapshot)
        ),
        "pt02_saldo_identificado": int(
            df_snapshot[
                "saldo_pt02_identificado"
            ].sum()
        ),
        "pt02_saldo_nao_identificado": int(
            df_snapshot[
                "saldo_pt02_identificado"
            ]
            .eq(False)
            .sum()
        ),
        "pt02_f5_positivo": int(
            (
                df_snapshot["saldo_pt02_f5"]
                .fillna(0.0)
                > 0
            ).sum()
        ),
        "pt02_b5_positivo": int(
            (
                df_snapshot["saldo_pt02_b5"]
                .fillna(0.0)
                > 0
            ).sum()
        ),
        "t001_f5_positivo": int(
            (
                df_snapshot["saldo_t001_f5"]
                > 0
            ).sum()
        ),
        "t001_b5_positivo": int(
            (
                df_snapshot["saldo_t001_b5"]
                > 0
            ).sum()
        ),
    }

    return (
        df_snapshot,
        indicadores,
    )
