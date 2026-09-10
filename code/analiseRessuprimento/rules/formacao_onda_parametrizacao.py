from __future__ import annotations

import pandas as pd


# ============================================================
# FORMAÇÃO DE ONDAS DE PARAMETRIZAÇÃO
# ============================================================

def formar_onda_por_percentual_demanda(
    df_backlog: pd.DataFrame,
    percentual_alvo: float,
) -> tuple[pd.DataFrame, dict]:
    """
    Seleciona a menor sequência de materiais necessária para
    atingir um percentual-alvo da demanda total do backlog.

    Premissas:
    - o backlog já foi priorizado pela regra oficial;
    - menor número de prioridade = maior prioridade;
    - demanda_relevante é a métrica exclusiva de priorização;
    - a linha que ultrapassa o percentual-alvo permanece na onda.

    Exemplo:
        alvo = 50%

        Se as linhas anteriores acumulam 49,8% e a próxima leva
        o acumulado para 50,2%, essa próxima linha pertence à onda.

    A função não acessa banco de dados e não grava nenhuma informação.
    """

    # --------------------------------------------------------
    # 1. Validações de entrada
    # --------------------------------------------------------

    if df_backlog is None:
        raise ValueError(
            "O backlog de parametrização não foi informado."
        )

    if df_backlog.empty:
        raise ValueError(
            "O backlog de parametrização está vazio."
        )

    if percentual_alvo <= 0 or percentual_alvo > 100:
        raise ValueError(
            "O percentual-alvo deve ser maior que 0 "
            "e menor ou igual a 100."
        )

    colunas_obrigatorias = {
        "prioridade",
        "material",
        "demanda_relevante",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(df_backlog.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "O backlog não possui as colunas obrigatórias: "
            + ", ".join(sorted(colunas_ausentes))
        )

    # --------------------------------------------------------
    # 2. Preparar backlog
    # --------------------------------------------------------

    df = df_backlog.copy()

    df["demanda_relevante"] = pd.to_numeric(
        df["demanda_relevante"],
        errors="raise",
    )

    if df["demanda_relevante"].isna().any():
        raise ValueError(
            "Existem valores nulos em demanda_relevante."
        )

    if (df["demanda_relevante"] <= 0).any():
        raise ValueError(
            "Todos os materiais do backlog devem possuir "
            "demanda_relevante positiva."
        )

    # A prioridade oficial já vem calculada pela regra anterior.
    # Ordenamos explicitamente para não depender da ordem física
    # recebida no DataFrame.
    df = df.sort_values(
        by=[
            "prioridade",
            "material",
        ],
        ascending=[
            True,
            True,
        ],
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # 3. Calcular demanda acumulada
    # --------------------------------------------------------

    demanda_total_backlog = float(
        df["demanda_relevante"].sum()
    )

    if demanda_total_backlog <= 0:
        raise ValueError(
            "A demanda total do backlog deve ser maior que zero."
        )

    df["demanda_acumulada"] = (
        df["demanda_relevante"].cumsum()
    )

    df["pct_demanda_acumulada"] = (
        df["demanda_acumulada"]
        / demanda_total_backlog
        * 100
    )

    # --------------------------------------------------------
    # 4. Identificar menor conjunto que atinge o alvo
    # --------------------------------------------------------

    mascara_alvo = (
        df["pct_demanda_acumulada"]
        >= percentual_alvo
    )

    if not mascara_alvo.any():
        # Em condições normais isso só poderia acontecer por
        # problema numérico, pois a última linha chega a 100%.
        raise RuntimeError(
            "Não foi possível atingir o percentual-alvo "
            "com o backlog informado."
        )

    indice_limite = mascara_alvo.idxmax()

    df_onda = (
        df.iloc[: indice_limite + 1]
        .copy()
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # 5. Indicadores da onda
    # --------------------------------------------------------

    demanda_total_onda = float(
        df_onda["demanda_relevante"].sum()
    )

    percentual_real_cobertura = (
        demanda_total_onda
        / demanda_total_backlog
        * 100
    )

    indicadores = {
        "percentual_alvo": float(percentual_alvo),
        "qtd_backlog": int(len(df)),
        "demanda_total_backlog": demanda_total_backlog,
        "qtd_materiais_onda": int(len(df_onda)),
        "demanda_total_onda": demanda_total_onda,
        "percentual_real_cobertura": float(
            percentual_real_cobertura
        ),
    }

    return df_onda, indicadores
