from __future__ import annotations

import pandas as pd

from analiseEstoques.scripts.streamlit_app import adicionar_indicador_giro


def test_giro_classifica_meta_e_preserva_dataframe_original() -> None:
    origem = pd.DataFrame(
        {
            "grupo": ["NA META", "ACIMA", "ABAIXO"],
            "entradas_val": [120.0, 150.0, 119.0],
            "saldo_atual_sap_val": [100.0, 100.0, 100.0],
        }
    )

    resultado = adicionar_indicador_giro(origem, meta_giro=1.2)

    assert "giro_atual" not in origem.columns
    assert resultado["giro_atual"].tolist() == [1.2, 1.5, 1.19]
    assert resultado["status_giro"].tolist() == [
        "🟢 META ATINGIDA",
        "🟢 META ATINGIDA",
        "🔴 ABAIXO DA META",
    ]


def test_giro_nao_calcula_com_saldo_zero_ou_negativo() -> None:
    origem = pd.DataFrame(
        {
            "entradas_val": [10.0, 0.0, 25.0],
            "saldo_atual_sap_val": [0.0, -1.0, None],
        }
    )

    resultado = adicionar_indicador_giro(origem, meta_giro=1.2)

    assert resultado["giro_atual"].isna().all()
    assert resultado["status_giro"].tolist() == [
        "⚪ NÃO CALCULADO",
        "⚪ NÃO CALCULADO",
        "⚪ NÃO CALCULADO",
    ]
