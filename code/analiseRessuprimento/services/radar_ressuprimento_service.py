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

TIPOS_ANALISE_PARAMETRIZACAO = [
    "MIN/MAX pendentes ou inconsistentes",
    "Saldo acima do MAX",
    "Reposição excessiva ou alta",
    "Reposição recorrente",
]

STATUS_MIN_MAX_PENDENTES_OU_INCONSISTENTES = {
    "PARAMETRIZAÇÃO PENDENTE",
    "PARAMETRIZAÇÃO INCOMPLETA",
    "PARÂMETROS MIN/MAX INVÁLIDOS",
    "PARÂMETROS MIN/MAX A REVISAR",
}


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
    tipos_analise: list[str] | None = None,
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

    if tipos_analise:
        tipos_desconhecidos = set(tipos_analise) - set(
            TIPOS_ANALISE_PARAMETRIZACAO
        )
        if tipos_desconhecidos:
            raise ValueError(
                "Tipos de análise desconhecidos: "
                + ", ".join(sorted(tipos_desconhecidos))
            )

        status = fila["status_parametrizacao_pt02"]
        ciclos = pd.to_numeric(
            fila.get(
                "ciclos_estimados_mes",
                pd.Series(pd.NA, index=fila.index),
            ),
            errors="coerce",
        )
        mascara = pd.Series(False, index=fila.index)

        if "MIN/MAX pendentes ou inconsistentes" in tipos_analise:
            mascara |= status.isin(
                STATUS_MIN_MAX_PENDENTES_OU_INCONSISTENTES
            )
        if "Saldo acima do MAX" in tipos_analise:
            mascara |= status.eq(
                "REVISAR MIN/MAX — SALDO ACIMA DO MAX"
            )
        if "Reposição excessiva ou alta" in tipos_analise:
            mascara |= ciclos.gt(4.0)
        if "Reposição recorrente" in tipos_analise:
            mascara |= ciclos.gt(1.0) & ciclos.le(4.0)

        fila = fila[mascara]

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


# ============================================================
# LISTA CRÍTICA E PLANO DE RETIRADAS POR POSIÇÃO T001
# ============================================================

def preparar_criticos_ressuprimento(radar: pd.DataFrame) -> pd.DataFrame:
    """Seleciona todos os críticos; 50% exatos ficam fora.

    O corte usa a média analítica, antes do arredondamento para peças.
    A quantidade sugerida continua sendo a recomposição até 100% da média,
    já calculada pelo motor. Conflitos PT02 permanecem no quadro de auditoria.
    """
    if radar.empty:
        return radar.copy()
    media = pd.to_numeric(radar["media_mensal_saida"], errors="coerce")
    saldo = pd.to_numeric(radar["saldo_pt02_f5"], errors="coerce")
    return radar.loc[
        media.gt(0) & saldo.lt(media * 0.5) & ~radar["duplicidade_pt02"]
    ].copy().reset_index(drop=True)


def _unidade_compativel(valor: object) -> str:
    """Normaliza a grafia sem converter ou presumir equivalência de unidades."""
    if pd.isna(valor):
        return ""
    texto = str(valor).strip().upper()
    return texto


def preparar_retiradas_t001(
    criticos: pd.DataFrame,
    origens: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Distribui a sugestão entre origens F5 e retorna pendências por SKU.

    Prioridade da origem: maior número de SKUs críticos atendíveis; empate
    pelo maior saldo movimentável do material e depois pelo endereço. É uma heurística de agrupamento, não um otimizador de rota
    ou de pallets (os dados atuais não identificam a unidade de transporte).
    Cada linha informa somente a quantidade a retirar naquela origem.
    Nenhuma reserva ou transferência é gravada no banco.
    """
    import math
    from rules.ressuprimento_pt02 import UNIDADES_DISCRETAS
    from repositories.estoque_repository import POSICAO_T001_EM_PROCESSO

    colunas = ["posicao_t001", "material", "descricao_material", "posicao",
               "unidade_operacional", "media_mensal_saida", "saldo_pt02_f5",
               "saldo_origem_f5", "quantidade_retirar", "status_saldo_pt02",
               "status_parametrizacao_pt02"]
    colunas_pendencia = ["material", "descricao_material", "posicao",
                        "unidade_operacional", "necessidade_operacional",
                        "quantidade_planejada", "quantidade_pendente", "motivo"]
    if criticos.empty:
        return pd.DataFrame(columns=colunas), pd.DataFrame(columns=colunas_pendencia)
    if criticos["material"].duplicated().any():
        raise ValueError("O plano exige uma única PT02 definitiva por material.")

    base = origens.copy()
    # Mesmo sem origens, produzimos as pendências de todos os críticos.
    if base.empty:
        base = pd.DataFrame(columns=["material", "posicao_t001",
                                     "unidade_medida", "saldo_origem_f5"])
    base["material"] = base["material"].astype(str).str.strip()
    base["posicao_t001"] = base["posicao_t001"].fillna("").astype(str).str.strip()
    # Defesa adicional para dados recebidos diretamente de outros consumidores.
    # O repository também exclui essa etapa do saldo agregado do radar.
    base = base.loc[
        base["posicao_t001"].str.upper().ne(POSICAO_T001_EM_PROCESSO)
    ].copy()
    base["_unidade"] = base["unidade_medida"].map(_unidade_compativel)
    base["saldo_origem_f5"] = pd.to_numeric(
        base["saldo_origem_f5"], errors="coerce"
    ).fillna(0.0)
    base = base.groupby(["material", "posicao_t001", "_unidade"], as_index=False)[
        "saldo_origem_f5"
    ].sum()
    # Uma origem/material com unidades incompatíveis é ambígua: não a usamos.
    ambiguos = base.groupby(["material", "posicao_t001"])["_unidade"].nunique()
    ambiguos = set(ambiguos[ambiguos.gt(1)].index)
    unidades = {str(r["material"]).strip(): _unidade_compativel(r["unidade_operacional"])
                for _, r in criticos.iterrows()}
    base = base.loc[
        base.apply(lambda r: bool(unidades.get(r["material"]))
                   and r["_unidade"] == unidades.get(r["material"])
                   and (r["material"], r["posicao_t001"]) not in ambiguos,
                   axis=1)
    ].copy() if not base.empty else base
    base = base.loc[base["posicao_t001"].ne("") & base["saldo_origem_f5"].gt(0)].copy()
    discretos = {_unidade_compativel(u) for u in UNIDADES_DISCRETAS}
    base["_disponivel"] = [
        float(math.floor(q)) if u in discretos else float(q)
        for q, u in zip(base["saldo_origem_f5"], base["_unidade"])
    ]
    base = base.loc[base["_disponivel"].gt(0)]
    acionaveis = set(criticos.loc[criticos["quantidade_sugerida"].gt(0), "material"].astype(str))
    ranking = base.loc[base["material"].isin(acionaveis)].groupby(
        "posicao_t001"
    )["material"].nunique().to_dict()
    base["_skus"] = base["posicao_t001"].map(ranking).fillna(0)
    base = base.sort_values(["_skus", "posicao_t001"], ascending=[False, True])
    linhas, pendencias = [], []
    for _, item in criticos.iterrows():
        material = str(item["material"]).strip()
        necessidade = max(float(item["necessidade_operacional"]), 0.0)
        # A sugestão do motor é um teto: nunca excedemos demanda ou estoque
        # agregado, mesmo quando a lista de origens apresenta mais saldo.
        restante = min(max(float(item["quantidade_sugerida"]), 0.0), necessidade)
        planejada = 0.0
        candidatas = base.loc[base["material"].eq(material)].sort_values(
            ["_skus", "_disponivel", "posicao_t001"], ascending=[False, False, True]
        )
        for _, origem in candidatas.iterrows():
            if restante <= 1e-9:
                break
            retirar = min(restante, float(origem["_disponivel"]))
            if retirar <= 0:
                continue
            linha = {c: item.get(c, "") for c in colunas}
            linha.update(posicao_t001=origem["posicao_t001"],
                         saldo_origem_f5=float(origem["saldo_origem_f5"]),
                         quantidade_retirar=retirar)
            linhas.append(linha)
            planejada += retirar
            restante -= retirar
        pendente = max(necessidade - planejada, 0.0)
        if pendente > 1e-9:
            if not unidades.get(material):
                motivo = "UMB ausente ou conflitante: validar antes de retirar"
            elif float(item["saldo_t001_f5"]) <= 0:
                motivo = "Sem saldo livre F5 na T001"
            elif restante > 1e-9:
                motivo = "Saldo por origem insuficiente ou UMB incompatível: conferir snapshot"
            else:
                motivo = "Saldo T001 insuficiente para completar a média mensal"
            pendencias.append(dict(material=material,
                descricao_material=item["descricao_material"], posicao=item["posicao"],
                unidade_operacional=item["unidade_operacional"],
                necessidade_operacional=necessidade, quantidade_planejada=planejada,
                quantidade_pendente=pendente, motivo=motivo))
    plano = pd.DataFrame(linhas, columns=colunas)
    if not plano.empty:
        plano["_skus"] = plano["posicao_t001"].map(ranking)
        plano = plano.sort_values(["_skus", "posicao_t001", "material"],
                                 ascending=[False, True, True]).drop(columns="_skus")
    return plano.reset_index(drop=True), pd.DataFrame(pendencias, columns=colunas_pendencia)
