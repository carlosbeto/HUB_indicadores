from __future__ import annotations

import sqlite3

import pandas as pd

from repositories.demanda_repository import carregar_demanda_material
from repositories.estoque_repository import (
    carregar_saldo_pt02_atual,
    carregar_saldo_t001_por_material,
)
from repositories.posicao_repository import carregar_pt02_atuais_binmat


# ============================================================
# CONFIGURAÇÕES DA REGRA
# ============================================================

POSICOES_TRANSICAO = {
    "PT02-001-002-001",
    "PT02-003-053-001",
}

TIPO_ESTOQUE_LIVRE = "F5"
TIPO_ESTOQUE_BLOQUEADO = "B5"


# ============================================================
# PREPARAÇÃO DOS SALDOS PT02
# ============================================================

def _consolidar_saldo_pt02(
    df_saldo_pt02: pd.DataFrame,
) -> pd.DataFrame:
    """
    Converte as linhas F5/B5 da PT02 em uma linha por
    material + posição.

    Importante:
    - ausência de F5 permanece ausente;
    - ausência de B5 pode ser interpretada como zero;
    - quantidade_disponivel é a referência operacional.
    """

    if df_saldo_pt02.empty:
        return pd.DataFrame(
            columns=[
                "material",
                "posicao",
                "saldo_pt02_f5",
                "saldo_pt02_b5",
                "f5_identificado",
            ]
        )

    base = (
        df_saldo_pt02[
            [
                "material",
                "posicao",
                "tipo_estoque",
                "quantidade_disponivel",
            ]
        ]
        .copy()
    )

    saldo = base.pivot_table(
        index=[
            "material",
            "posicao",
        ],
        columns="tipo_estoque",
        values="quantidade_disponivel",
        aggfunc="sum",
    ).reset_index()

    # Presença da coluna F5 significa que existe pelo menos
    # alguma linha F5 no conjunto. Precisamos preservar
    # individualmente quais material/posição possuem F5.
    if TIPO_ESTOQUE_LIVRE in saldo.columns:
        saldo["f5_identificado"] = (
            saldo[TIPO_ESTOQUE_LIVRE].notna()
        )
        saldo["saldo_pt02_f5"] = saldo[
            TIPO_ESTOQUE_LIVRE
        ]
    else:
        saldo["f5_identificado"] = False
        saldo["saldo_pt02_f5"] = pd.NA

    if TIPO_ESTOQUE_BLOQUEADO in saldo.columns:
        saldo["saldo_pt02_b5"] = (
            saldo[TIPO_ESTOQUE_BLOQUEADO]
            .fillna(0.0)
        )
    else:
        saldo["saldo_pt02_b5"] = 0.0

    return saldo[
        [
            "material",
            "posicao",
            "saldo_pt02_f5",
            "saldo_pt02_b5",
            "f5_identificado",
        ]
    ]


# ============================================================
# CLASSIFICAÇÃO OPERACIONAL
# ============================================================

def _classificar_status(
    linha: pd.Series,
) -> str:
    """
    Classifica a situação operacional da PT02.

    Ordem das regras é intencional.
    """

    minimo = linha["quantidade_minima"]
    maximo = linha["quantidade_maxima"]

    # --------------------------------------------
    # Sem parametrização
    # --------------------------------------------

    if minimo == 0 and maximo == 0:
        return "PARAMETRIZAÇÃO PENDENTE"

    # --------------------------------------------
    # Proteção para parametrização incompleta
    # --------------------------------------------

    if pd.isna(minimo) or pd.isna(maximo):
        return "PARAMETRIZAÇÃO INCOMPLETA"

    # --------------------------------------------
    # Consistência dos parâmetros MIN/MAX
    # --------------------------------------------

    if maximo < minimo:
        return "PARÂMETROS MIN/MAX INVÁLIDOS"

    if maximo == minimo:
        return "PARÂMETROS MIN/MAX A REVISAR"

    # --------------------------------------------
    # Sem saldo F5 identificado na fotografia
    # --------------------------------------------

    if not bool(linha["f5_identificado"]):
        return "SALDO PT02 NÃO IDENTIFICADO"

    saldo_pt02 = float(
        linha["saldo_pt02_f5"]
    )

    # --------------------------------------------
    # Acima do MIN
    # --------------------------------------------

    if saldo_pt02 > minimo:
        return "SEM NECESSIDADE"

    # --------------------------------------------
    # Atingiu ou ficou abaixo do MIN
    # --------------------------------------------

    necessidade = max(
        float(maximo) - saldo_pt02,
        0.0,
    )

    saldo_t001 = float(
        linha["saldo_t001_f5"]
    )

    if necessidade <= 0:
        return "SEM NECESSIDADE"

    if saldo_t001 <= 0:
        return "SEM SALDO T001"

    if saldo_t001 < necessidade:
        return "RESSUPRIR PARCIAL"

    return "RESSUPRIR"


# ============================================================
# RADAR OPERACIONAL
# ============================================================

def calcular_radar_ressuprimento_pt02(
    conn: sqlite3.Connection,
    meses: int = 6,
) -> tuple[pd.DataFrame, dict]:
    """
    Constrói o radar operacional de ressuprimento PT02.

    Princípios:
    - BINMAT define MIN/MAX;
    - VISAO_GERAL fornece a fotografia de estoque;
    - somente F5 é disponível para transferência;
    - B5 é apenas diagnóstico;
    - saldo <= MIN dispara avaliação de ressuprimento;
    - objetivo é abastecer em direção ao MAX;
    - todas as T001 atuais do material são agregadas;
    - demanda líquida de 6 meses ordena a prioridade;
    - demanda NÃO é o gatilho do ressuprimento.
    """

    # --------------------------------------------------------
    # 1. Fontes homologadas
    # --------------------------------------------------------

    df_posicoes = carregar_pt02_atuais_binmat(
        conn
    )

    df_saldo_pt02_raw = carregar_saldo_pt02_atual(
        conn
    )

    df_t001 = carregar_saldo_t001_por_material(
        conn
    )

    (
        df_demanda,
        data_inicio,
        data_referencia,
    ) = carregar_demanda_material(
        conn,
        meses=meses,
    )

    # --------------------------------------------------------
    # 2. PT02 definitivas
    # --------------------------------------------------------

    df = df_posicoes[
        ~df_posicoes["posicao"].isin(
            POSICOES_TRANSICAO
        )
    ].copy()

    # --------------------------------------------------------
    # 3. Consolidar e incorporar saldo PT02
    # --------------------------------------------------------

    df_saldo_pt02 = _consolidar_saldo_pt02(
        df_saldo_pt02_raw
    )

    df = df.merge(
        df_saldo_pt02,
        on=[
            "material",
            "posicao",
        ],
        how="left",
        validate="one_to_one",
    )

    # Ausência após LEFT JOIN significa que não encontramos
    # linha F5/B5 dessa PT02 na fotografia atual.
    df["f5_identificado"] = (
        df["f5_identificado"]
        .fillna(False)
        .astype(bool)
    )

    df["saldo_pt02_b5"] = (
        df["saldo_pt02_b5"]
        .fillna(0.0)
    )

    # --------------------------------------------------------
    # 4. Incorporar T001
    # --------------------------------------------------------

    df = df.merge(
        df_t001,
        on="material",
        how="left",
        validate="one_to_one",
    )

    colunas_t001_zero = [
        "qtd_posicoes_t001",
        "qtd_posicoes_t001_binmat",
        "saldo_t001_f5",
        "saldo_t001_b5",
    ]

    df[colunas_t001_zero] = (
        df[colunas_t001_zero]
        .fillna(0)
    )

    # --------------------------------------------------------
    # 5. Incorporar demanda
    # --------------------------------------------------------

    df = df.merge(
        df_demanda,
        on="material",
        how="left",
        validate="one_to_one",
    )

    colunas_demanda = [
        "qtd_601",
        "qtd_602",
        "qtd_z17",
        "qtd_z18",
        "demanda_comercial",
        "demanda_tecnica",
        "demanda_relevante",
    ]

    df[colunas_demanda] = (
        df[colunas_demanda]
        .fillna(0.0)
    )

    # --------------------------------------------------------
    # 6. Necessidade teórica até MAX
    # --------------------------------------------------------

    df["necessidade_ate_max"] = pd.NA

    mascara_calculavel = (
        df["f5_identificado"]
        & df["quantidade_maxima"].notna()
    )

    df.loc[
        mascara_calculavel,
        "necessidade_ate_max",
    ] = (
        df.loc[
            mascara_calculavel,
            "quantidade_maxima",
        ]
        - df.loc[
            mascara_calculavel,
            "saldo_pt02_f5",
        ]
    ).clip(lower=0)

    # --------------------------------------------------------
    # 7. Status operacional
    # --------------------------------------------------------

    df["status_operacional"] = df.apply(
        _classificar_status,
        axis=1,
    )

    # --------------------------------------------------------
    # 8. Quantidade sugerida
    # --------------------------------------------------------

    df["quantidade_sugerida"] = 0.0

    mascara_ressuprir = df[
        "status_operacional"
    ].isin(
        [
            "RESSUPRIR",
            "RESSUPRIR PARCIAL",
        ]
    )

    df.loc[
        mascara_ressuprir,
        "quantidade_sugerida",
    ] = (
        df.loc[
            mascara_ressuprir,
            [
                "necessidade_ate_max",
                "saldo_t001_f5",
            ],
        ]
        .astype(float)
        .min(axis=1)
    )

    # --------------------------------------------------------
    # 9. Diagnósticos de origem
    # --------------------------------------------------------

    df["possui_t001"] = (
        df["qtd_posicoes_t001"] > 0
    )

    df["t001_totalmente_parametrizada"] = (
        (df["qtd_posicoes_t001"] > 0)
        & (
            df["qtd_posicoes_t001"]
            == df["qtd_posicoes_t001_binmat"]
        )
    )

    df["possui_estoque_bloqueado_t001"] = (
        df["saldo_t001_b5"] > 0
    )

    # --------------------------------------------------------
    # 10. Prioridade de exibição
    # --------------------------------------------------------

    ordem_status = {
        "RESSUPRIR": 1,
        "RESSUPRIR PARCIAL": 1,
        "SEM SALDO T001": 1,
        "PARÂMETROS MIN/MAX INVÁLIDOS": 2,
        "PARÂMETROS MIN/MAX A REVISAR": 2,
        "SALDO PT02 NÃO IDENTIFICADO": 3,
        "PARAMETRIZAÇÃO PENDENTE": 4,
        "PARAMETRIZAÇÃO INCOMPLETA": 4,
        "SEM NECESSIDADE": 5,
    }

    df["_ordem_status"] = (
        df["status_operacional"]
        .map(ordem_status)
        .fillna(99)
    )

    df = df.sort_values(
        by=[
            "_ordem_status",
            "demanda_relevante",
            "material",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)

    df = df.drop(
        columns=["_ordem_status"]
    )

    # --------------------------------------------------------
    # 11. Indicadores de auditoria
    # --------------------------------------------------------

    contagem_status = (
        df["status_operacional"]
        .value_counts()
        .to_dict()
    )

    indicadores = {
        "data_inicio_demanda": data_inicio,
        "data_referencia_demanda": data_referencia,
        "meses_demanda": meses,
        "pt02_definitivas": len(df),
        "status": contagem_status,
    }

    return df, indicadores
