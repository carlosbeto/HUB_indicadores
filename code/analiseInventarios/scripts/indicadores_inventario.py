# code/analiseInventarios/scripts/indicadores_inventario.py
# -*- coding: utf-8 -*-

"""
Centraliza as regras de negócio dos indicadores de Inventários.

Os dashboards MM e EWM devem consumir os cálculos deste módulo,
evitando fórmulas duplicadas em diferentes telas.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def calcular_cobertura_semestral(
    df: pd.DataFrame,
    *,
    data_referencia: date,
) -> pd.DataFrame:
    """
    Calcula os indicadores acumulados do semestre.

    Regras principais:
    - meses passados e o mês corrente participam dos indicadores;
    - meses futuros permanecem no DataFrame, mas não participam
      dos cálculos realizados;
    - mês válido com zero contagens continua participando normalmente;
    - a média do baseline é progressiva entre os meses válidos;
    - as contagens são acumuladas entre os meses válidos;
    - a meta semestral cresce em sextos ao longo do semestre.

    Colunas geradas:
    - Período válido
    - Contados acumulado
    - Baseline médio
    - Cobertura semestre (%)
    - Mês índice
    - Meta semestre (%)
    - Gap semestre (%)
    """

    resultado = df.copy()

    colunas_obrigatorias = {"Mês", "Baseline", "Contados"}
    colunas_ausentes = colunas_obrigatorias.difference(resultado.columns)

    if colunas_ausentes:
        raise ValueError(
            "Colunas obrigatórias ausentes para cálculo semestral: "
            + ", ".join(sorted(colunas_ausentes))
        )

    resultado["Baseline"] = pd.to_numeric(
        resultado["Baseline"],
        errors="coerce",
    ).fillna(0)

    resultado["Contados"] = pd.to_numeric(
        resultado["Contados"],
        errors="coerce",
    ).fillna(0)

    # Converte o mês textual (YYYY-MM) para uma referência de calendário.
    # Essa informação é usada exclusivamente para decidir se o mês já ocorreu
    # ou se ainda é futuro em relação à data de referência.
    meses = pd.to_datetime(
        resultado["Mês"],
        format="%Y-%m",
        errors="coerce",
    )

    if meses.isna().any():
        meses_invalidos = resultado.loc[meses.isna(), "Mês"].astype(str).tolist()
        raise ValueError(
            "Existem valores inválidos na coluna 'Mês': "
            + ", ".join(meses_invalidos)
        )

    # Normaliza a data de referência para o primeiro dia do mês.
    # Assim a comparação considera somente ano/mês, e não o dia específico.
    mes_referencia = pd.Timestamp(
        year=data_referencia.year,
        month=data_referencia.month,
        day=1,
    )

    # Regra temporal oficial:
    # meses passados e o mês corrente são válidos;
    # meses futuros continuam no DataFrame para exibição,
    # mas não participam dos indicadores realizados.
    resultado["Período válido"] = meses <= mes_referencia

    # Para o baseline, meses futuros viram NaN propositalmente.
    # O expanding().mean() ignora NaN, impedindo que zeros artificiais
    # de meses futuros reduzam indevidamente a média progressiva.
    baseline_para_calculo = resultado["Baseline"].where(
        resultado["Período válido"]
    )

    # Para contagens, meses futuros contribuem com zero para o acumulado.
    # Um mês válido com Contados = 0 continua sendo preservado normalmente.
    contados_para_calculo = resultado["Contados"].where(
        resultado["Período válido"],
        0,
    )

    resultado["Contados acumulado"] = (
        contados_para_calculo
        .cumsum()
    )

    # Meses futuros não possuem um acumulado realizado.
    # O zero usado acima serve apenas para proteger o cálculo intermediário;
    # aqui removemos a aparência de que já existe resultado naquele mês.
    # O ~ significa, nesse contexto pandas, negação booleana.
    resultado.loc[
        ~resultado["Período válido"],
        "Contados acumulado",
    ] = pd.NA

    resultado["Baseline médio"] = (
        baseline_para_calculo
        .expanding()
        .mean()
    )

    # Indicadores acumulados representam somente períodos já realizados.
    # Embora o cálculo intermediário possa carregar o último valor adiante,
    # meses futuros não devem expor um indicador realizado.
    resultado.loc[
        ~resultado["Período válido"],
        "Baseline médio",
    ] = pd.NA

    resultado["Cobertura semestre (%)"] = pd.Series(
        pd.NA,
        index=resultado.index,
        dtype="Float64",
    )

    mask_calculo = (
        resultado["Período válido"]
        & resultado["Baseline médio"].notna()
        & (resultado["Baseline médio"] > 0)
    )

    resultado.loc[mask_calculo, "Cobertura semestre (%)"] = (
        resultado.loc[mask_calculo, "Contados acumulado"]
        / resultado.loc[mask_calculo, "Baseline médio"]
        * 100
    ).round(2)

    resultado["Mês índice"] = range(1, len(resultado) + 1)

    meta_mensal = 100.0 / 6.0

    resultado["Meta semestre (%)"] = pd.Series(
        pd.NA,
        index=resultado.index,
        dtype="Float64",
    )

    resultado.loc[
        resultado["Período válido"],
        "Meta semestre (%)",
    ] = (
        resultado.loc[
            resultado["Período válido"],
            "Mês índice",
        ]
        * meta_mensal
    ).round(2)

    resultado["Gap semestre (%)"] = (
        resultado["Cobertura semestre (%)"]
        - resultado["Meta semestre (%)"]
    ).round(2)

    return resultado
