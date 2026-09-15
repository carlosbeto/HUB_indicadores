from __future__ import annotations

"""Página de riscos que exigem atuação do PCP.

O abastecedor recebe somente transferências possíveis. Esta página apresenta
as necessidades sem cobertura na T001 e os resíduos que permanecem depois de
um ressuprimento parcial, sempre reutilizando o mesmo radar central.
"""

import sqlite3

import pandas as pd
import streamlit as st

from rules.ressuprimento_pt02 import (
    calcular_radar_ressuprimento_pt02,
)
from services.radar_ressuprimento_service import (
    preparar_fila_risco_pcp,
)
from ui.ressuprimento_pt02 import (
    _formatar_numero_br,
    _formatar_numero_operacional_br,
    _formatar_quantidade,
    _formatar_quantidade_operacional,
)


COLUNAS_RISCO_PCP = {
    "material": "Material",
    "descricao_material": "Descrição",
    "posicao": "Posição PT02",
    "media_mensal_saida": "Média mensal",
    "saldo_pt02_f5": "Saldo PT02 F5",
    "necessidade_operacional": "Necessidade",
    "saldo_t001_f5": "Saldo T001 F5",
    "quantidade_sugerida": "Ação possível",
    "quantidade_risco_pcp": "Risco não atendido",
    "unidade_operacional": "UMB",
    "status_operacional": "Situação",
    "status_parametrizacao_pt02": "Parametrização",
}


def _formatar_fila_pcp(
    fila: pd.DataFrame,
) -> pd.DataFrame:
    """Cria uma cópia legível sem modificar os números do radar."""

    exibicao = (
        fila[list(COLUNAS_RISCO_PCP)]
        .rename(columns=COLUNAS_RISCO_PCP)
        .copy()
    )

    exibicao["Média mensal"] = exibicao[
        "Média mensal"
    ].map(_formatar_numero_br)

    for coluna in [
        "Saldo PT02 F5",
        "Necessidade",
        "Saldo T001 F5",
        "Ação possível",
        "Risco não atendido",
    ]:
        exibicao[coluna] = exibicao.apply(
            lambda linha: _formatar_numero_operacional_br(
                linha[coluna],
                linha["UMB"],
            ),
            axis=1,
        )

    return exibicao


def render_risco_abastecimento_pcp(
    conn: sqlite3.Connection,
    *,
    usuario: dict,
) -> None:
    """Renderiza riscos integrais e residuais ordenados pela demanda."""

    st.title("Risco de abastecimento — PCP")
    st.caption(
        f"Usuário: {usuario['nome']} — {usuario['matricula']}"
    )

    # Assim como no radar do abastecedor, a leitura não usa cache nesta fase.
    # Após cada ETL, a página deve refletir o snapshot mais recente do estoque.
    radar, indicadores = calcular_radar_ressuprimento_pt02(
        conn,
        meses=6,
    )

    contagem_status = indicadores["status_operacional"]
    sem_saldo = contagem_status.get("SEM SALDO T001", 0)
    parciais = contagem_status.get("RESSUPRIR PARCIAL", 0)
    total_riscos = sem_saldo + parciais

    st.caption(
        "Janela móvel da demanda: "
        f"{indicadores['data_inicio_demanda'].strftime('%d/%m/%Y')} a "
        f"{indicadores['data_referencia_demanda'].strftime('%d/%m/%Y')}"
    )

    coluna_total, coluna_sem_saldo, coluna_parcial = st.columns(3)
    coluna_total.metric("Materiais em risco", total_riscos)
    coluna_sem_saldo.metric("Sem saldo T001", sem_saldo)
    coluna_parcial.metric("Cobertura parcial", parciais)

    st.info(
        "Esta visão não é uma fila de transferência. Ela orienta o PCP sobre "
        "demandas que a T001 não consegue atender integralmente."
    )

    st.subheader("Prioridades para o PCP")
    st.caption(
        "A ordem continua sendo definida pela maior demanda média mensal. "
        "Nos casos parciais, o risco mostra somente o saldo não atendido."
    )

    limite = st.slider(
        "Quantidade de riscos exibidos",
        min_value=10,
        max_value=100,
        value=20,
        step=10,
        format="Top %d",
        key="limite_fila_risco_pcp",
    )

    fila = preparar_fila_risco_pcp(
        radar,
        limite=limite,
    )

    if fila.empty:
        st.success(
            "Nenhum risco de abastecimento foi identificado para o PCP."
        )
        return

    evento = st.dataframe(
        _formatar_fila_pcp(fila),
        width="stretch",
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="fila_risco_abastecimento_pcp",
    )

    linhas_selecionadas = evento.selection.rows

    if not linhas_selecionadas:
        st.info(
            "Selecione um material para visualizar a composição do risco."
        )
        return

    item = fila.iloc[linhas_selecionadas[0]]
    unidade = item["unidade_operacional"]

    st.divider()
    st.subheader(
        f"Detalhe do risco — {item['material']}"
    )
    st.caption(
        f"{item['descricao_material']} | "
        f"PT02: {item['posicao']} | UMB: {unidade}"
    )

    necessidade, disponivel, acao, risco = st.columns(4)
    necessidade.metric(
        "Necessidade operacional",
        _formatar_quantidade_operacional(
            item["necessidade_operacional"],
            unidade,
        ),
    )
    disponivel.metric(
        "Saldo T001 F5",
        _formatar_quantidade_operacional(
            item["saldo_t001_f5"],
            unidade,
        ),
    )
    acao.metric(
        "Ação possível",
        _formatar_quantidade_operacional(
            item["quantidade_sugerida"],
            unidade,
        ),
    )
    risco.metric(
        "Risco não atendido",
        _formatar_quantidade_operacional(
            item["quantidade_risco_pcp"],
            unidade,
        ),
    )

    st.write(
        "**Composição:** "
        f"{_formatar_quantidade_operacional(item['necessidade_operacional'], unidade)} "
        "− "
        f"{_formatar_quantidade_operacional(item['quantidade_sugerida'], unidade)} "
        "= "
        f"{_formatar_quantidade_operacional(item['quantidade_risco_pcp'], unidade)}"
    )

    st.write(
        "**Média mensal:** "
        f"{_formatar_quantidade(item['media_mensal_saida'], unidade)} | "
        "**Saldo PT02 F5:** "
        f"{_formatar_quantidade_operacional(item['saldo_pt02_f5'], unidade)}"
    )

    st.write(
        "**Demanda comercial:** "
        f"{_formatar_quantidade(item['demanda_comercial'], unidade)} | "
        "**Demanda técnica:** "
        f"{_formatar_quantidade(item['demanda_tecnica'], unidade)}"
    )

    if item["status_operacional"] == "RESSUPRIR PARCIAL":
        st.warning(
            "O abastecedor pode executar uma transferência parcial, mas a "
            "quantidade destacada continuará sem cobertura."
        )
    else:
        st.error(
            "Não existe saldo livre F5 na T001 para atender esta necessidade."
        )

    if item["status_parametrizacao_pt02"] != "PARAMETRIZADA":
        st.warning(
            "A posição também requer atenção na BINMAT: "
            f"{item['status_parametrizacao_pt02']}."
        )
