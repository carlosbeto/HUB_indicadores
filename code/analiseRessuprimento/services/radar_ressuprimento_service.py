from __future__ import annotations

"""Preparação da fila que será apresentada no Streamlit.

O motor em ``rules.ressuprimento_pt02`` calcula e ordena as urgências. Este
serviço não repete essa regra: ele apenas seleciona os itens que realmente
necessitam de abastecimento e aplica o limite escolhido pelo controlador.
"""

import pandas as pd


def preparar_fila_prioritaria(
    radar: pd.DataFrame,
    *,
    limite: int,
) -> pd.DataFrame:
    """Retorna as primeiras urgências do radar até o limite informado.

    Uma cópia é devolvida para impedir que filtros ou formatações futuras da
    interface modifiquem acidentalmente o DataFrame completo do cálculo.
    """

    if limite <= 0:
        raise ValueError(
            "O limite da fila deve ser maior que zero."
        )

    if radar.empty:
        return radar.copy()

    fila = radar[
        radar["necessidade_ressuprimento"] > 0
    ]

    # A ordem já foi estabelecida pelo motor e está documentada pela coluna
    # prioridade_urgencia. ``head`` somente materializa o Top N escolhido.
    return fila.head(limite).copy()
