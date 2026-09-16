from __future__ import annotations

"""Preparação da fila que será apresentada no Streamlit.

O motor em ``rules.ressuprimento_pt02`` calcula e ordena as urgências. Este
serviço não repete essa regra: ele apenas seleciona os itens que realmente
necessitam de abastecimento e aplica o limite escolhido pelo controlador.
"""

import re

import pandas as pd


STATUS_ACIONAVEIS_ABASTECEDOR = {
    "RESSUPRIR",
    "RESSUPRIR PARCIAL",
}

STATUS_RISCO_PCP = {
    "SEM SALDO T001",
    "RESSUPRIR PARCIAL",
}

STATUS_PARAMETRIZACAO_REGULAR = "PARAMETRIZADA"


def _validar_limite(limite: int) -> None:
    """Protege os dois recortes contra um limite inválido."""

    if limite <= 0:
        raise ValueError(
            "O limite da fila deve ser maior que zero."
        )


def preparar_fila_prioritaria(
    radar: pd.DataFrame,
    *,
    limite: int,
) -> pd.DataFrame:
    """Retorna as primeiras urgências do radar até o limite informado.

    Uma cópia é devolvida para impedir que filtros ou formatações futuras da
    interface modifiquem acidentalmente o DataFrame completo do cálculo.
    """

    _validar_limite(limite)

    if radar.empty:
        return radar.copy()

    # A necessidade sem saldo na origem continua existindo no radar central,
    # mas não representa uma transferência executável pelo abastecedor.
    fila = radar[
        radar["status_operacional"].isin(
            STATUS_ACIONAVEIS_ABASTECEDOR
        )
    ]

    # A ordem já foi estabelecida pelo motor e está documentada pela coluna
    # prioridade_urgencia. ``head`` somente materializa o Top N escolhido.
    return fila.head(limite).copy()


def preparar_fila_risco_pcp(
    radar: pd.DataFrame,
    *,
    limite: int,
) -> pd.DataFrame:
    """Retorna demandas que a T001 não consegue atender integralmente.

    Itens sem saldo geram risco igual à necessidade total. Nos casos
    parciais, o abastecedor executa a parcela disponível e o PCP recebe
    somente a quantidade residual que continuará sem cobertura.
    """

    _validar_limite(limite)

    if radar.empty:
        fila_vazia = radar.copy()
        fila_vazia["quantidade_risco_pcp"] = pd.Series(
            dtype="float64"
        )
        return fila_vazia

    fila = radar[
        radar["status_operacional"].isin(
            STATUS_RISCO_PCP
        )
    ].copy()

    fila["quantidade_risco_pcp"] = (
        pd.to_numeric(
            fila["necessidade_operacional"],
            errors="coerce",
        ).fillna(0.0)
        - pd.to_numeric(
            fila["quantidade_sugerida"],
            errors="coerce",
        ).fillna(0.0)
    ).clip(lower=0.0)

    # Assim como na fila do abastecedor, o serviço preserva a prioridade pela
    # demanda já calculada e apenas aplica o limite escolhido na interface.
    return fila.head(limite).copy()


def preparar_fila_parametrizacao(
    radar: pd.DataFrame,
    *,
    diagnosticos: list[str] | None = None,
    busca: str = "",
    limite: int | None = None,
) -> pd.DataFrame:
    """Prepara a lista viva de posições que exigem atenção na BINMAT.

    A fila nasce sempre do radar atual. Nenhum item é assumido ou concluído:
    depois de uma nova carga BINMAT, uma posição corrigida deixa de atender ao
    filtro e desaparece naturalmente. A maior demanda define a prioridade.
    """

    if limite is not None:
        _validar_limite(limite)

    if radar.empty:
        return radar.copy()

    fila = radar[
        radar["status_parametrizacao_pt02"]
        != STATUS_PARAMETRIZACAO_REGULAR
    ].copy()

    if diagnosticos:
        fila = fila[
            fila["status_parametrizacao_pt02"].isin(
                diagnosticos
            )
        ]

    busca_normalizada = busca.strip()

    if busca_normalizada:
        padrao = re.escape(busca_normalizada)
        mascara = pd.Series(False, index=fila.index)

        for coluna in [
            "material",
            "descricao_material",
            "posicao",
        ]:
            mascara = mascara | fila[coluna].astype(str).str.contains(
                padrao,
                case=False,
                na=False,
            )

        fila = fila[mascara]

    fila = fila.sort_values(
        by=[
            "media_mensal_saida",
            "saldo_pt02_fisico",
            "material",
        ],
        ascending=[False, False, True],
    )

    if limite is not None:
        fila = fila.head(limite)

    return fila.reset_index(drop=True)
