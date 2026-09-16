from __future__ import annotations

"""Fila dinâmica para revisão dos parâmetros MIN/MAX da PT02.

A página é somente leitura. O controlador recebe uma lista atualizada, atua
fisicamente e no SAP em lote e, após o próximo ETL BINMAT, as posições
corrigidas deixam de aparecer automaticamente.
"""

import sqlite3

import pandas as pd
import streamlit as st

from rules.ressuprimento_pt02 import calcular_radar_ressuprimento_pt02
from services.radar_ressuprimento_service import preparar_fila_parametrizacao
from ui.ressuprimento_pt02 import (
    _formatar_numero_operacional_br,
    _formatar_quantidade_operacional,
)


COLUNAS_PARAMETRIZACAO = {
    "material": "Material",
    "descricao_material": "Descrição",
    "posicao": "Posição PT02",
    "media_mensal_operacional": "Média mensal",
    "quantidade_minima": "MIN atual",
    "quantidade_maxima": "MAX atual",
    "saldo_pt02_f5": "Saldo F5",
    "saldo_pt02_b5": "Saldo B5",
    "saldo_pt02_fisico": "Saldo físico",
    "unidade_operacional": "UMB",
    "status_parametrizacao_pt02": "Diagnóstico",
}


def _formatar_fila_parametrizacao(fila: pd.DataFrame) -> pd.DataFrame:
    """Cria uma cópia legível sem alterar os números do radar."""

    exibicao = (
        fila[list(COLUNAS_PARAMETRIZACAO)]
        .rename(columns=COLUNAS_PARAMETRIZACAO)
        .copy()
    )

    for coluna in [
        "Média mensal",
        "MIN atual",
        "MAX atual",
        "Saldo F5",
        "Saldo B5",
        "Saldo físico",
    ]:
        exibicao[coluna] = exibicao.apply(
            lambda linha: _formatar_numero_operacional_br(
                linha[coluna],
                linha["UMB"],
            ),
            axis=1,
        )

    return exibicao


def _gerar_csv_parametrizacao(fila: pd.DataFrame) -> bytes:
    """Exporta toda a seleção filtrada em formato amigável ao Excel PT-BR."""

    # O arquivo deve reproduzir a apresentação operacional da tela:
    # unidades discretas não exibem casas decimais e unidades fracionáveis
    # preservam duas casas. A formatação atua somente na cópia exportada;
    # os valores numéricos usados pelo radar permanecem inalterados.
    exportacao = _formatar_fila_parametrizacao(fila)

    return exportacao.to_csv(
        index=False,
        sep=";",
    ).encode("utf-8-sig")


def render_parametrizacao(
    conn: sqlite3.Connection,
    *,
    usuario: dict,
) -> None:
    """Renderiza a lista atual de posições PT02 que exigem revisão."""

    st.title("Parametrização BINMAT — Fila dinâmica")
    st.caption(f"Usuário: {usuario['nome']} — {usuario['matricula']}")

    radar, indicadores = calcular_radar_ressuprimento_pt02(conn, meses=6)

    fila_completa = preparar_fila_parametrizacao(radar)
    contagem = indicadores["status_parametrizacao_pt02"]

    total_atencao = len(fila_completa)
    pendentes = contagem.get("PARAMETRIZAÇÃO PENDENTE", 0)
    acima_max = contagem.get(
        "REVISAR MIN/MAX — SALDO ACIMA DO MAX",
        0,
    )
    outros = total_atencao - pendentes - acima_max

    st.caption(
        "Janela móvel da demanda: "
        f"{indicadores['data_inicio_demanda'].strftime('%d/%m/%Y')} a "
        f"{indicadores['data_referencia_demanda'].strftime('%d/%m/%Y')} | "
        f"PT02 analisadas: {indicadores['pt02_definitivas']}"
    )

    coluna_total, coluna_pendente, coluna_max, coluna_outros = st.columns(4)
    coluna_total.metric("Posições com atenção", total_atencao)
    coluna_pendente.metric("MIN/MAX pendentes", pendentes)
    coluna_max.metric("Saldo acima do MAX", acima_max)
    coluna_outros.metric("Outras inconsistências", outros)

    st.info(
        "A fila não exige conclusão manual. Depois do ajuste no SAP e de "
        "uma nova carga BINMAT, as posições corrigidas desaparecem "
        "automaticamente."
    )

    st.subheader("Lista de trabalho do controlador")
    st.caption(
        "A ordem é definida pela maior demanda mensal. Use os filtros para "
        "preparar um lote de trabalho por diagnóstico, material ou posição."
    )

    diagnosticos_disponiveis = sorted(
        fila_completa["status_parametrizacao_pt02"]
        .dropna()
        .unique()
        .tolist()
    )

    coluna_filtro, coluna_busca = st.columns([2, 1])

    with coluna_filtro:
        diagnosticos = st.multiselect(
            "Diagnósticos",
            options=diagnosticos_disponiveis,
            default=diagnosticos_disponiveis,
            key="diagnosticos_parametrizacao_binmat",
        )

    with coluna_busca:
        busca = st.text_input(
            "Buscar material, descrição ou posição",
            key="busca_parametrizacao_binmat",
        )

    fila_filtrada = preparar_fila_parametrizacao(
        radar,
        diagnosticos=diagnosticos,
        busca=busca,
    )

    limite = st.slider(
        "Quantidade de posições exibidas",
        min_value=10,
        max_value=500,
        value=50,
        step=10,
        format="Top %d",
        key="limite_parametrizacao_binmat",
    )

    fila_exibida = fila_filtrada.head(limite).copy()

    coluna_resultado, coluna_exportacao = st.columns([3, 1])
    coluna_resultado.caption(
        f"Exibindo {len(fila_exibida)} de "
        f"{len(fila_filtrada)} posições filtradas."
    )

    with coluna_exportacao:
        st.download_button(
            "Exportar seleção filtrada",
            data=_gerar_csv_parametrizacao(fila_filtrada),
            file_name="parametrizacao_binmat_pt02.csv",
            mime="text/csv",
            disabled=fila_filtrada.empty,
        )

    if fila_exibida.empty:
        st.success("Nenhuma posição corresponde aos filtros selecionados.")
        return

    evento = st.dataframe(
        _formatar_fila_parametrizacao(fila_exibida),
        width="stretch",
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="fila_parametrizacao_binmat",
    )

    linhas_selecionadas = evento.selection.rows

    if not linhas_selecionadas:
        st.info(
            "Selecione uma posição para visualizar os dados que justificam "
            "o diagnóstico."
        )
        return

    item = fila_exibida.iloc[linhas_selecionadas[0]]
    unidade = item["unidade_operacional"]

    st.divider()
    st.subheader(f"Detalhe da posição — {item['material']}")
    st.caption(
        f"{item['descricao_material']} | "
        f"PT02: {item['posicao']} | UMB: {unidade}"
    )

    coluna_media, coluna_min, coluna_max, coluna_fisico = st.columns(4)
    coluna_media.metric(
        "Média mensal",
        _formatar_quantidade_operacional(
            item["media_mensal_operacional"], unidade
        ),
    )
    coluna_min.metric(
        "MIN atual",
        _formatar_quantidade_operacional(item["quantidade_minima"], unidade),
    )
    coluna_max.metric(
        "MAX atual",
        _formatar_quantidade_operacional(item["quantidade_maxima"], unidade),
    )
    coluna_fisico.metric(
        "Saldo físico PT02",
        _formatar_quantidade_operacional(item["saldo_pt02_fisico"], unidade),
    )

    st.write(
        "**Composição do saldo físico:** "
        f"F5 {_formatar_quantidade_operacional(item['saldo_pt02_f5'], unidade)} "
        "+ "
        f"B5 {_formatar_quantidade_operacional(item['saldo_pt02_b5'], unidade)}"
    )
    st.warning(
        "Diagnóstico BINMAT: "
        f"{item['status_parametrizacao_pt02']}"
    )
