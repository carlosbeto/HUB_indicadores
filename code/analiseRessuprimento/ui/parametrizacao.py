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
from services.radar_ressuprimento_service import (
    TIPOS_ANALISE_PARAMETRIZACAO,
    preparar_fila_parametrizacao,
)
from ui.ressuprimento_pt02 import (
    _formatar_numero_operacional_br,
    _formatar_quantidade_operacional,
)


COLUNAS_PARAMETRIZACAO = {
    "material": "Material",
    "descricao_material": "Descrição",
    "posicao": "Posição PT02",
    "media_mensal_operacional": "Consumo médio/mês",
    "quantidade_minima": "MIN no SAP",
    "quantidade_maxima": "MAX no SAP",
    "lote_teorico_reposicao": "Qtd. por reposição",
    "ciclos_estimados_mes": "Reposições estimadas/mês",
    "intervalo_estimado_dias_uteis": "Dias úteis entre reposições",
    "saldo_pt02_f5": "Saldo livre PT02",
    "saldo_pt02_b5": "Saldo bloqueado PT02",
    "saldo_pt02_fisico": "Ocupação atual PT02",
    "unidade_operacional": "UMB",
    "classificacao_frequencia_reposicao": "Nível de frequência",
    "status_parametrizacao_pt02": "Ação recomendada",
}


ORIENTACOES_DIAGNOSTICO = {
    "PARAMETRIZAÇÃO PENDENTE": (
        "Medir a capacidade da posição e cadastrar MIN e MAX no SAP."
    ),
    "PARAMETRIZAÇÃO INCOMPLETA": (
        "Completar no SAP o parâmetro MIN ou MAX que está ausente."
    ),
    "PARÂMETROS MIN/MAX INVÁLIDOS": (
        "Corrigir o SAP: o MAX precisa ser maior que o MIN."
    ),
    "PARÂMETROS MIN/MAX A REVISAR": (
        "Revisar o SAP: MIN e MAX iguais não formam lote de reposição."
    ),
    "REVISAR MIN/MAX — SALDO ACIMA DO MAX": (
        "Conferir a capacidade física: a posição contém mais material do "
        "que o MAX cadastrado permite."
    ),
    "REVISAR MIN/MAX — REPOSIÇÃO EXCESSIVA": (
        "Redimensionar a posição com prioridade para reduzir reposições "
        "diárias repetidas."
    ),
    "REVISAR MIN/MAX — ALTA FREQUÊNCIA": (
        "Avaliar aumento do lote ou da capacidade para reduzir o retrabalho "
        "de abastecimento."
    ),
    "AVALIAR DIMENSIONAMENTO — REPOSIÇÃO RECORRENTE": (
        "Verificar se a posição pode comportar um lote maior e exigir menos "
        "reposições durante o mês."
    ),
}


def _formatar_decimal_br(valor: object) -> str:
    """Formata indicadores contínuos com duas casas no padrão brasileiro."""

    if pd.isna(valor):
        return "Não calculado"

    formato = f"{float(valor):,.2f}"
    return formato.replace(",", "#").replace(".", ",").replace("#", ".")


def _formatar_fila_parametrizacao(fila: pd.DataFrame) -> pd.DataFrame:
    """Cria uma cópia legível sem alterar os números do radar."""

    exibicao = (
        fila[list(COLUNAS_PARAMETRIZACAO)]
        .rename(columns=COLUNAS_PARAMETRIZACAO)
        .copy()
    )

    for coluna in [
        "Consumo médio/mês",
        "MIN no SAP",
        "MAX no SAP",
        "Qtd. por reposição",
        "Saldo livre PT02",
        "Saldo bloqueado PT02",
        "Ocupação atual PT02",
    ]:
        exibicao[coluna] = exibicao.apply(
            lambda linha: _formatar_numero_operacional_br(
                linha[coluna],
                linha["UMB"],
            ),
            axis=1,
        )

    exibicao["Reposições estimadas/mês"] = exibicao[
        "Reposições estimadas/mês"
    ].map(
        _formatar_decimal_br
    )
    exibicao["Dias úteis entre reposições"] = exibicao[
        "Dias úteis entre reposições"
    ].map(
        _formatar_decimal_br
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
    frequencia = int(
        (
            pd.to_numeric(
                radar["ciclos_estimados_mes"],
                errors="coerce",
            )
            > 1
        ).sum()
    )
    status_frequencia = {
        "AVALIAR DIMENSIONAMENTO — REPOSIÇÃO RECORRENTE",
        "REVISAR MIN/MAX — ALTA FREQUÊNCIA",
        "REVISAR MIN/MAX — REPOSIÇÃO EXCESSIVA",
    }
    outros = sum(
        quantidade
        for status, quantidade in contagem.items()
        if status not in (
            status_frequencia
            | {
                "PARAMETRIZADA",
                "PARAMETRIZAÇÃO PENDENTE",
                "REVISAR MIN/MAX — SALDO ACIMA DO MAX",
            }
        )
    )

    st.caption(
        "Janela móvel da demanda: "
        f"{indicadores['data_inicio_demanda'].strftime('%d/%m/%Y')} a "
        f"{indicadores['data_referencia_demanda'].strftime('%d/%m/%Y')} | "
        f"PT02 analisadas: {indicadores['pt02_definitivas']}"
    )

    (
        coluna_total,
        coluna_pendente,
        coluna_max,
        coluna_frequencia,
        coluna_outros,
    ) = st.columns(5)
    coluna_total.metric("Posições com atenção", total_atencao)
    coluna_pendente.metric("MIN/MAX pendentes", pendentes)
    coluna_max.metric("Saldo acima do MAX", acima_max)
    coluna_frequencia.metric("Reposição acima de 1 ciclo/mês", frequencia)
    coluna_outros.metric("Outras inconsistências", outros)

    st.info(
        "A fila não exige conclusão manual. Depois do ajuste no SAP e de "
        "uma nova carga BINMAT, as posições corrigidas desaparecem "
        "automaticamente."
    )

    with st.expander("Como usar esta tela", expanded=True):
        st.markdown(
            """
1. **Escolha um ou mais tipos de análise** conforme o trabalho que será realizado.
2. **Defina o Top 10, 20, 50...** para preparar um lote viável de posições.
3. **Selecione uma posição** e confira a causa e a ação recomendada.
4. **Verifique fisicamente a capacidade** antes de alterar MIN/MAX no SAP.
5. Depois do ajuste, execute os ETLs. A posição regularizada deixa a fila.

**Como o esforço é estimado:** a quantidade por reposição é `MAX − MIN`.
O consumo médio mensal dividido por esse lote estima quantas reposições serão
necessárias no mês. O intervalo usa 22 dias úteis apenas como referência.
            """
        )

    st.subheader("Lista de trabalho do controlador")
    st.caption(
        "A ferramenta indica onde investigar; ela não define sozinha o novo "
        "MIN/MAX. A ordem continua sendo definida pelo maior consumo médio."
    )

    coluna_filtro, coluna_busca = st.columns([2, 1])

    with coluna_filtro:
        tipos_analise = st.multiselect(
            "Tipos de análise",
            options=TIPOS_ANALISE_PARAMETRIZACAO,
            default=[],
            placeholder="Vazio = mostrar todos os itens com atenção",
            key="tipo_analise_parametrizacao_binmat",
        )

    with coluna_busca:
        busca = st.text_input(
            "Buscar material, descrição ou posição",
            key="busca_parametrizacao_binmat",
        )

    fila_filtrada = preparar_fila_parametrizacao(
        radar,
        tipos_analise=tipos_analise,
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
    coluna_resultado.caption(
        "Os indicadores de saldo e frequência podem apontar a mesma posição; "
        "o total considera cada posição apenas uma vez."
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

    coluna_lote, coluna_ciclos, coluna_intervalo = st.columns(3)
    coluna_lote.metric(
        "Lote teórico (MAX − MIN)",
        _formatar_quantidade_operacional(
            item["lote_teorico_reposicao"],
            unidade,
        ),
    )
    coluna_ciclos.metric(
        "Ciclos estimados/mês",
        _formatar_decimal_br(item["ciclos_estimados_mes"]),
    )
    intervalo = _formatar_decimal_br(
        item["intervalo_estimado_dias_uteis"]
    )
    coluna_intervalo.metric(
        "Intervalo estimado",
        (
            intervalo
            if intervalo == "Não calculado"
            else f"{intervalo} dias úteis"
        ),
    )

    st.caption(
        "Frequência estimada: "
        f"{item['classificacao_frequencia_reposicao']}"
    )

    st.write(
        "**Composição do saldo físico:** "
        f"F5 {_formatar_quantidade_operacional(item['saldo_pt02_f5'], unidade)} "
        "+ "
        f"B5 {_formatar_quantidade_operacional(item['saldo_pt02_b5'], unidade)}"
    )
    st.warning(
        "Ação recomendada: "
        f"{item['status_parametrizacao_pt02']}"
    )
    st.info(
        ORIENTACOES_DIAGNOSTICO.get(
            item["status_parametrizacao_pt02"],
            "Revisar os dados da posição antes de alterar o SAP.",
        )
    )
