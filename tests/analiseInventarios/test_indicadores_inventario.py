from datetime import date

import pandas as pd
import pytest

from analiseInventarios.scripts.indicadores_inventario import (
    calcular_cobertura_semestral,
)


def test_calcula_falta_para_meta_em_agosto():
    """
    Valida um cenário conhecido do 2º semestre.

    Julho:
    - baseline = 1200
    - contados = 200

    Agosto:
    - baseline = 1300
    - contados = 100

    Em agosto:
    - baseline médio = 1250
    - contados acumulados = 300
    - meta acumulada = 33,33%
    - meta em itens = 417
    - faltam 117 itens para atingir a meta
    """

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [1200, 1300, 0, 0, 0, 0],
            "Contados": [200, 100, 0, 0, 0, 0],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2026, 8, 20),
    )

    agosto = resultado.loc[
        resultado["Mês"] == "2026-08"
    ].iloc[0]

    assert agosto["Baseline médio"] == 1250.0
    assert agosto["Contados acumulado"] == 300.0
    assert agosto["Meta semestre (%)"] == 33.33
    assert agosto["Meta semestre (itens)"] == 417
    assert agosto["Falta contar para meta (itens)"] == 117
    assert agosto["Falta contar para meta semestral (itens)"] == 117


def test_separa_falta_mensal_da_falta_semestral():
    """A folga acumulada não deve esconder o atraso isolado do mês."""

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [7202, 6971, 6994, 0, 0, 0],
            "Contados": [1407, 1546, 678, 0, 0, 0],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2026, 9, 24),
    )

    setembro = resultado.loc[
        resultado["Mês"] == "2026-09"
    ].iloc[0]

    assert setembro["Meta mensal (itens)"] == 1166
    assert setembro["Falta contar para meta mensal (itens)"] == 488
    assert setembro["Falta contar para meta semestral (itens)"] == 0
    assert setembro["Falta contar para meta (itens)"] == 0

def test_mes_valido_com_zero_contagens_participa_do_calculo():
    """
    Garante que um mês já ocorrido continua válido mesmo sem contagens.

    Agosto possui:
    - baseline = 1300
    - contados = 0

    Mesmo assim, agosto deve:
    - permanecer como período válido;
    - participar do baseline médio;
    - manter o acumulado de contagens de julho;
    - calcular normalmente a cobertura e a meta do semestre.
    """

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [1200, 1300, 0, 0, 0, 0],
            "Contados": [600, 0, 0, 0, 0, 0],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2026, 8, 20),
    )

    agosto = resultado.loc[
        resultado["Mês"] == "2026-08"
    ].iloc[0]

    assert agosto["Período válido"] == True
    assert agosto["Baseline médio"] == 1250.0
    assert agosto["Contados acumulado"] == 600.0
    assert agosto["Cobertura semestre (%)"] == 48.0
    assert agosto["Meta semestre (%)"] == 33.33
    assert agosto["Gap semestre (%)"] == 14.67

def test_meses_futuros_nao_geram_indicadores_realizados():
    """
    Garante que meses futuros permaneçam no calendário,
    mas não produzam indicadores realizados.
    """

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [1200, 1300, 0, 0, 0, 0],
            "Contados": [600, 0, 0, 0, 0, 0],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2026, 8, 20),
    )

    setembro = resultado.loc[
        resultado["Mês"] == "2026-09"
    ].iloc[0]

    assert setembro["Período válido"] == False
    assert pd.isna(setembro["Baseline médio"])
    assert pd.isna(setembro["Contados acumulado"])
    assert pd.isna(setembro["Cobertura semestre (%)"])
    assert pd.isna(setembro["Meta semestre (%)"])
    assert pd.isna(setembro["Gap semestre (%)"])
    assert pd.isna(setembro["Meta semestre (itens)"])
    assert pd.isna(setembro["Meta mensal (itens)"])
    assert pd.isna(setembro["Falta contar para meta mensal (itens)"])
    assert pd.isna(
        setembro["Falta contar para meta semestral (itens)"]
    )
    assert pd.isna(setembro["Falta contar para meta (itens)"])

def test_semestre_encerrado_considera_todos_os_meses_validos():
    """
    Quando a data de referência já está depois do semestre,
    todos os seis meses devem ser considerados válidos.
    """

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [1200, 1300, 1250, 1275, 1280, 1290],
            "Contados": [600, 0, 100, 120, 130, 140],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2027, 2, 1),
    )

    assert resultado["Período válido"].all()
    assert resultado["Meta semestre (%)"].iloc[-1] == 100.0
    assert pd.notna(resultado["Cobertura semestre (%)"].iloc[-1])
    assert pd.notna(resultado["Gap semestre (%)"].iloc[-1])


def test_semestre_futuro_nao_gera_indicadores_realizados():
    """
    Quando a data de referência ainda está antes do semestre,
    nenhum dos seis meses deve gerar indicadores realizados.
    """

    df = pd.DataFrame(
        {
            "Mês": [
                "2026-07",
                "2026-08",
                "2026-09",
                "2026-10",
                "2026-11",
                "2026-12",
            ],
            "Baseline": [1200, 1300, 1250, 1275, 1280, 1290],
            "Contados": [600, 0, 100, 120, 130, 140],
        }
    )

    resultado = calcular_cobertura_semestral(
        df,
        data_referencia=date(2026, 2, 1),
    )

    assert not resultado["Período válido"].any()
    assert resultado["Cobertura semestre (%)"].isna().all()
    assert resultado["Meta semestre (%)"].isna().all()
    assert resultado["Gap semestre (%)"].isna().all()
    assert resultado["Meta mensal (itens)"].isna().all()
    assert resultado[
        "Falta contar para meta mensal (itens)"
    ].isna().all()
    assert resultado[
        "Falta contar para meta semestral (itens)"
    ].isna().all()
    assert resultado["Falta contar para meta (itens)"].isna().all()

def test_erro_quando_falta_coluna_obrigatoria():
    """
    Garante que a função rejeite DataFrames sem todas as colunas
    necessárias para executar a regra semestral.
    """

    df = pd.DataFrame(
        {
            "Mês": ["2026-07"],
            "Baseline": [1200],
            # Coluna "Contados" ausente propositalmente.
        }
    )

    with pytest.raises(
        ValueError,
        match="Colunas obrigatórias ausentes",
    ):
        calcular_cobertura_semestral(
            df,
            data_referencia=date(2026, 7, 20),
        )


def test_erro_quando_mes_possui_formato_invalido():
    """
    Garante que valores inválidos na coluna Mês sejam rejeitados.
    """

    df = pd.DataFrame(
        {
            "Mês": ["2026-07", "agosto-2026"],
            "Baseline": [1200, 1300],
            "Contados": [200, 100],
        }
    )

    with pytest.raises(
        ValueError,
        match="Existem valores inválidos na coluna 'Mês'",
    ):
        calcular_cobertura_semestral(
            df,
            data_referencia=date(2026, 8, 20),
        )
