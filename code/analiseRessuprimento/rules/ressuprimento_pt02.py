from __future__ import annotations

# Versão de entrega: 2026-09-14, incluindo saldos F5 inferidos.

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
                "posicao_visao_geral_identificada",
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

    # Se a consolidação produziu a chave material + posição, sabemos que a
    # relação apareceu na VISAO_GERAL, ainda que somente com estoque B5.
    saldo["posicao_visao_geral_identificada"] = True

    return saldo[
        [
            "material",
            "posicao",
            "saldo_pt02_f5",
            "saldo_pt02_b5",
            "f5_identificado",
            "posicao_visao_geral_identificada",
        ]
    ]


# ============================================================
# CLASSIFICAÇÃO DA PARAMETRIZAÇÃO PT02
# ============================================================

def _classificar_parametrizacao_pt02(
    linha: pd.Series,
) -> str:
    """
    Diagnostica os parâmetros MIN/MAX sem decidir o ressuprimento.

    Essa separação é essencial: uma PT02 com MIN/MAX zerados ainda pode
    precisar de abastecimento quando seu saldo está abaixo da média mensal.
    """

    minimo = linha["quantidade_minima"]
    maximo = linha["quantidade_maxima"]

    # --------------------------------------------
    if minimo == 0 and maximo == 0:
        return "PARAMETRIZAÇÃO PENDENTE"

    # --------------------------------------------
    if pd.isna(minimo) or pd.isna(maximo):
        return "PARAMETRIZAÇÃO INCOMPLETA"

    # --------------------------------------------
    if maximo < minimo:
        return "PARÂMETROS MIN/MAX INVÁLIDOS"

    if maximo == minimo:
        return "PARÂMETROS MIN/MAX A REVISAR"

    return "PARAMETRIZADA"


# ============================================================
# CLASSIFICAÇÃO OPERACIONAL
# ============================================================

def _classificar_status_operacional(
    linha: pd.Series,
) -> str:
    """Classifica a necessidade pela média mensal e pelos saldos F5.

    A BINMAT não participa desta decisão. Primeiro identificamos se o picking
    precisa de estoque; depois informamos separadamente se os parâmetros
    MIN/MAX também exigem manutenção.
    """

    necessidade = float(
        linha["necessidade_ressuprimento"]
    )

    # Saldo igual ou superior à média mensal produz necessidade zero.
    if necessidade <= 0:
        return "SEM NECESSIDADE"

    saldo_t001 = float(
        linha["saldo_t001_f5"]
    )

    if saldo_t001 <= 0:
        return "SEM SALDO T001"

    if saldo_t001 < necessidade:
        return "RESSUPRIR PARCIAL"

    return "RESSUPRIR"


def _classificar_origem_saldo_pt02(
    linha: pd.Series,
) -> str:
    """Explica se o saldo F5 foi lido ou inferido como zero.

    A inferência permite emitir o alerta preventivo, enquanto este diagnóstico
    impede que o usuário confunda ausência no relatório com um zero informado
    explicitamente pelo SAP.
    """

    if bool(linha["f5_identificado"]):
        return "F5 INFORMADO"

    if bool(linha["posicao_visao_geral_identificada"]):
        return "SOMENTE B5 - F5 ASSUMIDO ZERO"

    return "AUSENTE NA VISAO GERAL - F5 ASSUMIDO ZERO"


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
    - a MB51 fornece a demanda líquida de uma janela móvel;
    - média mensal = demanda líquida / quantidade de meses;
    - VISAO_GERAL fornece a fotografia de estoque;
    - somente F5 é disponível para transferência;
    - B5 é apenas diagnóstico;
    - saldo PT02 abaixo da média mensal dispara a necessidade;
    - necessidade = média mensal - saldo PT02 F5;
    - todas as T001 atuais do material são agregadas;
    - o saldo T001 limita a quantidade que pode ser movimentada;
    - MIN/MAX são diagnóstico paralelo de parametrização.
    """

    # Embora o repository de demanda também valide este argumento, a regra
    # protege seu próprio contrato. Isso evita divisão por zero caso uma fonte
    # seja substituída em teste ou em uma futura integração.
    if meses <= 0:
        raise ValueError(
            "A quantidade de meses deve ser maior que zero."
        )

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

    # eq(True) converte tanto False quanto ausência do LEFT JOIN em False sem
    # depender do downcasting implícito do pandas, removendo o FutureWarning.
    df["f5_identificado"] = (
        df["f5_identificado"].eq(True)
    )

    df["posicao_visao_geral_identificada"] = (
        df["posicao_visao_geral_identificada"].eq(True)
    )

    # B5 ausente equivale a nenhum estoque bloqueado observado.
    df["saldo_pt02_b5"] = pd.to_numeric(
        df["saldo_pt02_b5"],
        errors="coerce",
    ).fillna(0.0)

    # Para a operação preventiva, F5 ausente é tratado como zero. Mantemos uma
    # coluna booleana e um diagnóstico textual para revelar que houve
    # inferência, e não leitura explícita do saldo.
    df["saldo_pt02_f5_inferido"] = (
        ~df["f5_identificado"]
    )

    df["saldo_pt02_f5"] = pd.to_numeric(
        df["saldo_pt02_f5"],
        errors="coerce",
    ).fillna(0.0)

    df["status_saldo_pt02"] = df.apply(
        _classificar_origem_saldo_pt02,
        axis=1,
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
    # 6. Média mensal da janela móvel
    # --------------------------------------------------------
    # carregar_demanda_material já limita os movimentos entre a maior data
    # disponível na MB51 e os seis meses anteriores. Neste ponto dividimos o
    # total líquido pelo número de meses solicitado.

    df["media_mensal_saida"] = (
        df["demanda_relevante"]
        / float(meses)
    )

    # --------------------------------------------------------
    # 7. Necessidade de ressuprimento pela demanda
    # --------------------------------------------------------
    # O saldo operacional já contém o valor informado ou zero inferido. Dessa
    # forma, todas as PT02 definitivas participam do mesmo cálculo.
    df["necessidade_ressuprimento"] = (
        df["media_mensal_saida"]
        - df["saldo_pt02_f5"]
    ).clip(lower=0)

    # --------------------------------------------------------
    # 8. Diagnóstico teórico até o MAX
    # --------------------------------------------------------
    # Este cálculo anterior é preservado como informação complementar para a
    # futura parametrização. Ele não decide mais se existe necessidade.

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
    # 9. Diagnóstico de parametrização e status operacional
    # --------------------------------------------------------

    df["status_parametrizacao_pt02"] = df.apply(
        _classificar_parametrizacao_pt02,
        axis=1,
    )

    df["status_operacional"] = df.apply(
        _classificar_status_operacional,
        axis=1,
    )

    # --------------------------------------------------------
    # 10. Quantidade sugerida
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
                "necessidade_ressuprimento",
                "saldo_t001_f5",
            ],
        ]
        .astype(float)
        .min(axis=1)
    )

    # --------------------------------------------------------
    # 11. Diagnósticos de origem
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
    # 12. Prioridade de exibição
    # --------------------------------------------------------

    ordem_status = {
        "RESSUPRIR": 1,
        "RESSUPRIR PARCIAL": 1,
        "SEM SALDO T001": 1,
        "SALDO PT02 NÃO IDENTIFICADO": 2,
        "SEM NECESSIDADE": 3,
    }

    df["_ordem_status"] = (
        df["status_operacional"]
        .map(ordem_status)
        .fillna(99)
    )

    df = df.sort_values(
        by=[
            "_ordem_status",
            "media_mensal_saida",
            "necessidade_ressuprimento",
            "material",
        ],
        ascending=[
            True,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    df = df.drop(
        columns=["_ordem_status"]
    )

    # --------------------------------------------------------
    # 13. Indicadores de auditoria
    # --------------------------------------------------------

    contagem_status_operacional = (
        df["status_operacional"]
        .value_counts()
        .to_dict()
    )

    contagem_status_parametrizacao = (
        df["status_parametrizacao_pt02"]
        .value_counts()
        .to_dict()
    )

    contagem_status_saldo_pt02 = (
        df["status_saldo_pt02"]
        .value_counts()
        .to_dict()
    )

    indicadores = {
        "data_inicio_demanda": data_inicio,
        "data_referencia_demanda": data_referencia,
        "meses_demanda": meses,
        "pt02_definitivas": len(df),
        # Mantemos status como alias do indicador anterior para não quebrar
        # consumidores existentes durante a evolução controlada da interface.
        "status": contagem_status_operacional,
        "status_operacional": contagem_status_operacional,
        "status_parametrizacao_pt02": (
            contagem_status_parametrizacao
        ),
        "status_saldo_pt02": contagem_status_saldo_pt02,
    }

    return df, indicadores
