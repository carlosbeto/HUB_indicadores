import sqlite3

import streamlit as st

from repositories.plano_parametrizacao_repository import (
    listar_fila_operacional_plano,
    obter_resumo_operacional_plano,
)

from services.plano_parametrizacao_service import (
    obter_detalhe_operacional_tarefa,
)


def render_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
) -> None:
    plano = obter_resumo_operacional_plano(
    conn,
    id_plano=id_plano,
)

    if plano is None:
        st.error(
            f"Plano {id_plano} não encontrado."
        )
        return

    fila = listar_fila_operacional_plano(
        conn,
        id_plano=id_plano,
    )

    st.title("Parametrização PT02")

    st.caption(
        f"Plano: {plano['nome']} | "
        f"Onda: {plano['onda']} | "
        f"Status: {plano['status']}"
    )

    st.subheader("Fila operacional")

    if not fila:
        st.info(
            "Nenhum item encontrado para este plano."
        )
        return

    evento = st.dataframe(
        fila,
        width="stretch",
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="fila_operacional",
    )

    linhas_selecionadas = evento.selection.rows

    if not linhas_selecionadas:
        st.info(
            "Selecione um material na fila para visualizar "
            "o detalhe operacional."
        )
        return

    indice_selecionado = linhas_selecionadas[0]

    item_selecionado = fila[indice_selecionado]

    id_item_plano = item_selecionado["id_item_plano"]

    detalhe = obter_detalhe_operacional_tarefa(
        conn,
        id_item_plano=id_item_plano,
    )

    item = detalhe["item"]
    snapshot = detalhe["snapshot_inicial"]
    binmat = detalhe["binmat_atual"]
    decisao = detalhe["decisao_ativa"]
    confirmacao = detalhe["ultima_confirmacao_sap"]

    st.divider()

    st.subheader(
        f"Detalhe operacional — {item['material']}"
    )

    st.caption(
        f"{item['descricao']} | "
        f"PT02: {item['posicao_pt02']} | "
        f"Prioridade: {item['prioridade']} | "
        f"Status: {item['status']}"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Demanda relevante",
            snapshot["demanda_relevante"],
        )

        st.metric(
            "Demanda comercial",
            snapshot["demanda_comercial"],
        )

        st.metric(
            "Demanda técnica",
            snapshot["demanda_tecnica"],
        )

    with col2:
        st.metric(
            "Saldo PT02 F5",
            snapshot["saldo_pt02_f5"],
        )

        st.metric(
            "Saldo T001 F5",
            snapshot["saldo_t001_f5"],
        )

        st.metric(
            "Qtd. posições T001",
            snapshot["qtd_posicoes_t001"],
        )

    with col3:
        st.metric(
            "MIN inicial",
            snapshot["min"],
        )

        st.metric(
            "MAX inicial",
            snapshot["max"],
        )

        st.metric(
            "% demanda acumulada",
            snapshot["pct_demanda_acumulada"],
        )

    st.write(
        "**Situação física inicial:** "
        f"{snapshot['situacao_fisica']}"
    )

    st.markdown("### BINMAT atual")

    if binmat["presente"]:
        st.write(
            f"MIN atual: **{binmat['min']}**  \n"
            f"MAX atual: **{binmat['max']}**  \n"
            f"Arquivo origem: `{binmat['arquivo_origem']}`"
        )
    else:
        st.warning(
            "A posição não está presente no snapshot BINMAT atual."
        )

    st.markdown("### Decisão")

    if decisao is None:
        st.info(
            "Este item ainda não possui decisão ativa."
        )
    else:
        st.write(
            f"Decisão: **{decisao['decisao']}**  \n"
            f"Revisão: **{decisao['numero_revisao']}**  \n"
            f"MIN proposto: **{decisao['min_proposto']}**  \n"
            f"MAX proposto: **{decisao['max_proposto']}**"
        )

    st.markdown("### Última confirmação SAP")

    if confirmacao is None:
        st.info(
            "Ainda não há confirmação SAP registrada."
        )
    else:
        st.write(
            f"Resultado: **{confirmacao['resultado']}**  \n"
            f"MIN encontrado: **{confirmacao['min_encontrado']}**  \n"
            f"MAX encontrado: **{confirmacao['max_encontrado']}**  \n"
            f"Verificado em: **{confirmacao['verificado_em']}**"
        )
