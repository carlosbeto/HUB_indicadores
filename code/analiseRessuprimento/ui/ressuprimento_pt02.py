from __future__ import annotations

"""Página de leitura do radar preventivo de ressuprimento PT02.

A interface apresenta resultados produzidos pelas camadas de regra e serviço.
Ela não recalcula prioridades e não grava ações no banco. Essa separação evita
que um componente visual altere silenciosamente uma regra operacional.
"""

import sqlite3

import pandas as pd
import streamlit as st

from rules.ressuprimento_pt02 import (
    UNIDADES_DISCRETAS,
    calcular_radar_ressuprimento_pt02,
)
from services.radar_ressuprimento_service import (
    preparar_fila_prioritaria,
)


COLUNAS_FILA = {
    "material": "Material",
    "descricao_material": "Descrição",
    "posicao": "Posição PT02",
    "media_mensal_operacional": "Média mensal",
    "saldo_pt02_f5": "Saldo PT02 F5",
    "necessidade_operacional": "Necessidade",
    "saldo_t001_f5": "Saldo T001 F5",
    "quantidade_sugerida": "Qtd. sugerida",
    "unidade_operacional": "UMB",
    "status_operacional": "Situação",
    "status_saldo_pt02": "Origem saldo PT02",
    "status_parametrizacao_pt02": "Parametrização",
}


def _formatar_numero_br(
    valor: object,
) -> str:
    """Apresenta um número com milhar e decimal no padrão brasileiro.

    O arredondamento para duas casas acontece somente no texto exibido. O
    valor numérico usado pelo radar não é substituído nem modificado.
    """

    if pd.isna(valor):
        return "Não informado"

    formato_internacional = f"{float(valor):,.2f}"

    return (
        formato_internacional
        .replace(",", "#")
        .replace(".", ",")
        .replace("#", ".")
    )


def _formatar_quantidade(
    valor: object,
    unidade: object,
) -> str:
    """Acrescenta a UMB ao número já formatado para apresentação.

    A função não converte unidades e não altera o valor calculado. Ela apenas
    produz, por exemplo, ``375,50 PEÇ`` para leitura humana.
    """

    if pd.isna(valor):
        return "Não informada"

    numero = _formatar_numero_br(valor)
    texto_unidade = "" if pd.isna(unidade) else f" {unidade}"

    return f"{numero}{texto_unidade}"


def _formatar_numero_operacional_br(
    valor: object,
    unidade: object,
) -> str:
    """Formata ação e saldo conforme a natureza física da UMB.

    A regra já entrega valores inteiros para unidades discretas. A interface
    apenas remove as casas ```,00``. Unidades fracionáveis continuam com duas
    casas. Nenhum arredondamento de negócio é realizado nesta função.
    """

    if pd.isna(valor):
        return "Não informado"

    unidade_normalizada = (
        ""
        if pd.isna(unidade)
        else str(unidade).strip().upper()
    )

    if unidade_normalizada in UNIDADES_DISCRETAS:
        formato_internacional = f"{float(valor):,.0f}"

        return formato_internacional.replace(",", ".")

    return _formatar_numero_br(valor)


def _formatar_quantidade_operacional(
    valor: object,
    unidade: object,
) -> str:
    """Acrescenta a UMB à quantidade operacional já calculada."""

    numero = _formatar_numero_operacional_br(
        valor,
        unidade,
    )

    if numero == "Não informado":
        return numero

    texto_unidade = "" if pd.isna(unidade) else f" {unidade}"

    return f"{numero}{texto_unidade}"


def _mostrar_alertas_item(
    item: pd.Series,
) -> None:
    """Explica condições que exigem atenção sem mudar a prioridade."""

    if float(item["saldo_pt02_f5"]) <= 0:
        st.warning(
            "O saldo livre F5 desta posição PT02 está zerado."
        )

    if item["status_saldo_pt02"] != "F5 INFORMADO":
        st.warning(
            "O saldo PT02 usado no cálculo não veio de uma linha F5 "
            f"explícita: {item['status_saldo_pt02']}."
        )

    if item["status_parametrizacao_pt02"] != "PARAMETRIZADA":
        st.warning(
            "A necessidade de ressuprimento foi calculada normalmente, "
            "mas a posição também requer atenção na BINMAT: "
            f"{item['status_parametrizacao_pt02']}."
        )

    if item["status_operacional"] == "SEM SALDO T001":
        st.error(
            "Existe necessidade no picking, porém não há saldo livre F5 "
            "na T001 para executar o ressuprimento."
        )
    elif item["status_operacional"] == "RESSUPRIR PARCIAL":
        st.warning(
            "A T001 permite atender somente parte da necessidade atual."
        )
    else:
        st.success(
            "Existe saldo livre F5 suficiente na T001 para a sugestão."
        )


def _mostrar_detalhe_material(item: pd.Series) -> None:
    """Exibe os valores do radar sem recalcular ou gravar ações."""

    unidade = item["unidade_operacional"]

    st.divider()
    st.subheader(
        f"Detalhe do material — {item['material']}"
    )
    st.caption(
        f"{item['descricao_material']} | "
        f"Destino: {item['posicao']} | "
        f"UMB: {unidade}"
    )

    demanda, picking, origem, sugestao = st.columns(4)

    demanda.metric(
        "Média mensal",
        _formatar_quantidade(
            item["media_mensal_saida"],
            unidade,
        ),
    )
    picking.metric(
        "Saldo PT02 F5",
        _formatar_quantidade_operacional(
            item["saldo_pt02_f5"],
            unidade,
        ),
    )
    origem.metric(
        "Saldo T001 F5",
        _formatar_quantidade_operacional(
            item["saldo_t001_f5"],
            unidade,
        ),
    )
    sugestao.metric(
        "Quantidade sugerida",
        _formatar_quantidade_operacional(
            item["quantidade_sugerida"],
            unidade,
        ),
    )

    st.write(
        "**Cálculo da necessidade:** "
        f"{_formatar_quantidade(item['media_mensal_saida'], unidade)} "
        "− "
        f"{_formatar_quantidade_operacional(item['saldo_pt02_f5'], unidade)} "
        "= "
        f"{_formatar_quantidade(item['necessidade_ressuprimento'], unidade)}"
    )

    st.write(
        "**Necessidade operacional:** "
        f"{_formatar_quantidade_operacional(item['necessidade_operacional'], unidade)}"
    )

    st.write(
        "**Demanda comercial:** "
        f"{_formatar_quantidade(item['demanda_comercial'], unidade)} | "
        "**Demanda técnica:** "
        f"{_formatar_quantidade(item['demanda_tecnica'], unidade)}"
    )

    st.write(f"**Situação:** {item['status_operacional']}")

    # A consulta também inclui situações que não permitem ressuprimento.
    # Os alertas da fila são adequados somente às três situações abaixo.
    if item["status_operacional"] in {
        "RESSUPRIR", "RESSUPRIR PARCIAL", "SEM SALDO T001"
    }:
        _mostrar_alertas_item(item)
    else:
        st.info("Confira a situação calculada pelo radar para este material.")


def render_ressuprimento_pt02(
    conn: sqlite3.Connection,
    *,
    usuario: dict,
) -> None:
    """Renderiza a fila diária priorizada pela demanda da MB51."""

    st.title("Radar preventivo — Ressuprimento PT02")
    st.caption(
        f"Usuário: {usuario['nome']} — {usuario['matricula']}"
    )

    # Não aplicamos cache nesta primeira versão: cada reconstrução da página
    # lê o banco atual, coerente com a natureza viva do estoque após os ETLs.
    radar, indicadores = calcular_radar_ressuprimento_pt02(
        conn,
        meses=6,
    )

    # A inconsistência de destino PT02 aparece antes da fila de ações.
    # Esses materiais permanecem no radar para auditoria, mas não entram
    # nas métricas operacionais nem em transferências sugeridas.
    duplicidades = radar.loc[radar["duplicidade_pt02"]].copy()
    radar_regular = radar.loc[~radar["duplicidade_pt02"]].copy()
    total_materiais_duplicados = indicadores[
        "qtd_materiais_duplicados_pt02"
    ]
    if total_materiais_duplicados:
        materiais = ", ".join(
            str(material)
            for material in indicadores["materiais_duplicados_pt02"]
        )
        st.header("🚨 CONFLITO DE POSIÇÕES PT02 — AÇÃO BLOQUEADA")
        st.error(
            f"{total_materiais_duplicados} material(is) aparecem em mais de "
            "uma posição PT02 definitiva na BINMAT. "
            f"Materiais: {materiais}. Não há transferência sugerida "
            "para eles. Confira abaixo todas as posições e regularize "
            "a origem dos dados; os demais materiais continuam na fila."
        )
        st.dataframe(
            duplicidades[
                [
                    "material",
                    "descricao_material",
                    "posicao",
                    "id_posicao_material",
                    "data_modificacao",
                ]
            ].rename(
                columns={
                    "material": "Material",
                    "descricao_material": "Descrição",
                    "posicao": "Posição PT02",
                    "id_posicao_material": "ID da posição",
                    "data_modificacao": "Modificação BINMAT",
                }
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        # O indicador sempre visível também confirma que a versão corrigida
        # da tela está em execução, mesmo quando não há conflitos no banco.
        st.info("Verificação BINMAT: 0 materiais com conflito PT02.")

    contagem_status = indicadores["status_operacional"]
    total_necessidade = int(
        (radar_regular["necessidade_ressuprimento"] > 0).sum()
    )
    total_acoes = (
        contagem_status.get("RESSUPRIR", 0)
        + contagem_status.get("RESSUPRIR PARCIAL", 0)
    )
    total_riscos_pcp = (
        contagem_status.get("SEM SALDO T001", 0)
        + contagem_status.get("RESSUPRIR PARCIAL", 0)
    )

    st.caption(
        "Janela móvel da demanda: "
        f"{indicadores['data_inicio_demanda'].strftime('%d/%m/%Y')} a "
        f"{indicadores['data_referencia_demanda'].strftime('%d/%m/%Y')} | "
        f"PT02 analisadas: {indicadores['pt02_definitivas']}"
    )

    coluna_total, coluna_completo, coluna_parcial, coluna_sem_saldo = (
        st.columns(4)
    )

    coluna_total.metric(
        "Ações possíveis",
        total_acoes,
    )
    coluna_completo.metric(
        "Ressuprir",
        contagem_status.get("RESSUPRIR", 0),
    )
    coluna_parcial.metric(
        "Ressuprir parcial",
        contagem_status.get("RESSUPRIR PARCIAL", 0),
    )
    coluna_sem_saldo.metric(
        "Encaminhados ao PCP",
        total_riscos_pcp,
    )

    st.caption(
        f"O radar identificou {total_necessidade} materiais com necessidade. "
        f"Destes, {total_acoes} permitem ação do abastecedor e "
        f"{total_riscos_pcp} possuem risco total ou residual para o PCP."
    )

    # Reserva um quinto da largura para a consulta por código.
    coluna_consulta, _ = st.columns([1, 4])
    with coluna_consulta:
        codigo_material = st.text_input(
            "Consultar código do material",
            value="",
            placeholder="Ex.: 1020283",
            help=(
                "Digite o código completo. A consulta usa todo o radar, "
                "sem o limite Top XX e sem restringir aos itens da fila. "
                "Limpe o campo para voltar à fila de prioridades."
            ),
            key="consulta_material_ressuprimento_pt02",
        ).strip()

    if codigo_material:
        # Busca exata no radar completo: inclui conflitos e materiais que
        # não permitem ação. Não altera indicadores nem a ordem da fila.
        consulta = radar.loc[
            radar["material"].astype(str).str.strip().eq(codigo_material)
        ].copy()

        st.subheader(f"Consulta do material — {codigo_material}")
        if consulta.empty:
            st.info(
                f"O material {codigo_material} não foi encontrado no radar "
                "PT02 atual. Isso não confirma sua ausência no cadastro; "
                "confira se possui posição PT02 definitiva nos dados atuais."
            )
            return

        # Conflitos exibem todas as posições, sem sugestão operacional.
        if consulta["duplicidade_pt02"].any():
            st.error(
                "CONFLITO DE POSIÇÕES PT02 — AÇÃO BLOQUEADA. "
                "Regularize as posições na origem dos dados."
            )
            st.dataframe(
                consulta[
                    ["material", "descricao_material", "posicao",
                     "id_posicao_material", "data_modificacao"]
                ].rename(columns={
                    "material": "Material",
                    "descricao_material": "Descrição",
                    "posicao": "Posição PT02",
                    "id_posicao_material": "ID da posição",
                    "data_modificacao": "Modificação BINMAT",
                }),
                width="stretch",
                hide_index=True,
            )
            return

        for _, item_consulta in consulta.iterrows():
            _mostrar_detalhe_material(item_consulta)
        return

    st.subheader("Fila de prioridades")
    st.caption(
        "Esta fila contém somente ressuprimentos completos ou parciais que "
        "podem ser executados. A ordem é definida pela demanda."
    )

    limite = st.slider(
        "Quantidade de itens exibidos",
        min_value=10,
        max_value=100,
        value=20,
        step=10,
        format="Top %d",
        key="limite_fila_ressuprimento_pt02",
    )

    fila = preparar_fila_prioritaria(
        radar_regular,
        limite=limite,
    )

    if fila.empty:
        st.success(
            "Nenhuma posição PT02 regular está apta a ressuprimento."
        )
        return

    fila_exibicao = (
        fila[list(COLUNAS_FILA)]
        .rename(columns=COLUNAS_FILA)
    )

    # A tabela recebe uma cópia textual para usar ponto nos milhares e
    # vírgula nos decimais. ``fila`` permanece numérica e será usada tanto na
    # seleção quanto no detalhe e em futuros comandos operacionais.
    fila_exibicao["Média mensal"] = fila_exibicao.apply(
        lambda linha: _formatar_numero_operacional_br(
            linha["Média mensal"],
            linha["UMB"],
        ),
        axis=1,
    )

    for coluna in [
        "Saldo PT02 F5",
        "Necessidade",
        "Saldo T001 F5",
        "Qtd. sugerida",
    ]:
        fila_exibicao[coluna] = fila_exibicao.apply(
            lambda linha: _formatar_numero_operacional_br(
                linha[coluna],
                linha["UMB"],
            ),
            axis=1,
        )

    evento = st.dataframe(
        fila_exibicao,
        width="stretch",
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="fila_prioritaria_ressuprimento_pt02",
    )

    linhas_selecionadas = evento.selection.rows

    if not linhas_selecionadas:
        st.info(
            "Selecione um material para compreender o cálculo e os alertas."
        )
        return

    item = fila.iloc[linhas_selecionadas[0]]
    _mostrar_detalhe_material(item)
