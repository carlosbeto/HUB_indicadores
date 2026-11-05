from __future__ import annotations

"""Página de leitura do radar preventivo de ressuprimento PT02.

A interface apresenta resultados produzidos pelas camadas de regra e serviço.
Ela não recalcula prioridades e não grava ações no banco. Essa separação evita
que um componente visual altere silenciosamente uma regra operacional.
"""

import sqlite3
from io import BytesIO
from datetime import datetime

from repositories.estoque_repository import carregar_saldo_t001_por_posicao

import pandas as pd
import streamlit as st

from rules.ressuprimento_pt02 import (
    UNIDADES_DISCRETAS,
    calcular_radar_ressuprimento_pt02,
)
from services.radar_ressuprimento_service import (
    preparar_criticos_ressuprimento,
    preparar_retiradas_t001,
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


COLUNAS_RETIRADAS = {
    "posicao_t001": "Origem T001", "material": "Material",
    "descricao_material": "Descrição", "posicao": "Destino PT02",
    "unidade_operacional": "UMB", "media_mensal_saida": "Média mensal",
    "saldo_pt02_f5": "Saldo PT02 F5", "saldo_origem_f5": "Saldo origem F5",
    "quantidade_retirar": "Qtd. retirar nesta origem",
    "status_saldo_pt02": "Origem saldo PT02",
    "status_parametrizacao_pt02": "Parametrização",
}
COLUNAS_PENDENCIAS = {
    "material": "Material", "descricao_material": "Descrição",
    "posicao": "Destino PT02", "unidade_operacional": "UMB",
    "necessidade_operacional": "Necessidade total",
    "quantidade_planejada": "Qtd. planejada",
    "quantidade_pendente": "Qtd. pendente", "motivo": "Motivo",
}


def _tabela_exportacao(df: pd.DataFrame, colunas: dict) -> pd.DataFrame:
    """Preserva números e identificadores, inclusive em tabelas vazias."""
    return df.reindex(columns=list(colunas)).rename(columns=colunas).copy()


def gerar_excel_ressuprimento(
    criticos: pd.DataFrame, retiradas: pd.DataFrame,
    pendencias: pd.DataFrame, conflitos: pd.DataFrame, indicadores: dict,
) -> bytes:
    """Gera a lista integral em memória, sem gravar dados operacionais."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    memoria = BytesIO()
    tabelas = {
        "Retiradas por origem": _tabela_exportacao(retiradas, COLUNAS_RETIRADAS),
        "Criticos": _tabela_exportacao(criticos, {
            **COLUNAS_FILA, "media_mensal_saida": "Média mensal analítica",
        }),
        "Pendencias": _tabela_exportacao(pendencias, COLUNAS_PENDENCIAS),
        "Conflitos PT02": _tabela_exportacao(conflitos, {
            "material": "Material", "descricao_material": "Descrição",
            "posicao": "Posição PT02", "id_posicao_material": "ID da posição",
            "data_modificacao": "Modificação BINMAT",
        }),
        "Criterios": pd.DataFrame([
            ("Geração", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
            ("Janela da demanda", str(indicadores["data_inicio_demanda"])
             + " a " + str(indicadores["data_referencia_demanda"])),
            ("Criticidade", "Saldo PT02 F5 < 50% da média mensal analítica; média > 0"),
            ("Quantidade", "Completar 100% da média, com arredondamento operacional existente e limite T001"),
            ("Origem", "Somente F5 atual em T001; unidades compatíveis; B5 não abastece"),
            ("Agrupamento", "Mais SKUs críticos por posição; empate pelo saldo do material e endereço"),
            ("Execução", "Somar apenas Qtd. retirar nesta origem por material; saldos de destino repetem em múltiplas origens"),
            ("Limitações", "Snapshot sem reserva; conferir saldo físico e capacidade PT02 antes da execução"),
            ("Pallets", "Posição não identifica necessariamente um único pallet"),
            ("MIN/MAX", "Diagnóstico preservado: não é limite da sugestão atual"),
            ("Conflitos", "Materiais com duplicidade PT02 não recebem retiradas"),
        ], columns=["Critério", "Definição"]),
    }
    with pd.ExcelWriter(memoria, engine="openpyxl") as writer:
        for nome, tabela in tabelas.items():
            tabela.to_excel(writer, sheet_name=nome, index=False)
            ws = writer.sheets[nome]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.sheet_view.showGridLines = False
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E78")
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[1].height = 32
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    if isinstance(cell.value, str):
                        # Identificadores/descritivos são texto literal, mesmo
                        # quando começam por '=': nunca são fórmulas do Excel.
                        cell.data_type = "s"
                    elif isinstance(cell.value, (int, float)):
                        cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(vertical="top")
            for idx, titulo in enumerate(tabela.columns, 1):
                valores = tabela.iloc[:, idx - 1].fillna("").astype(str)
                largura = max(len(str(titulo)), max(map(len, valores), default=0)) + 2
                ws.column_dimensions[get_column_letter(idx)].width = min(max(largura, 12), 55)
            if nome == "Criterios":
                ws.column_dimensions["B"].width = 95
                for row in ws.iter_rows(min_row=2):
                    row[1].alignment = Alignment(wrap_text=True, vertical="top")
                    ws.row_dimensions[row[0].row].height = 42
            ws.print_title_rows = "1:1"
            ws.page_setup.orientation = "landscape"
            ws.page_setup.paperSize = ws.PAPERSIZE_A4
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.print_options.horizontalCentered = True
    return memoria.getvalue()


def render_ressuprimento_pt02(conn: sqlite3.Connection, *, usuario: dict) -> None:
    """Exibe os críticos e as retiradas agrupadas sem limite de registros."""
    st.title("Radar preventivo — Ressuprimento PT02")
    st.caption(f"Usuário: {usuario['nome']} — {usuario['matricula']}")
    radar, indicadores = calcular_radar_ressuprimento_pt02(conn, meses=6)
    conflitos = radar.loc[radar["duplicidade_pt02"]].copy()
    if not conflitos.empty:
        st.error("CONFLITO DE POSIÇÕES PT02 — AÇÃO BLOQUEADA. "
                 "Os materiais abaixo não recebem sugestão de retirada.")
        st.dataframe(_tabela_exportacao(conflitos, {
            "material": "Material", "descricao_material": "Descrição",
            "posicao": "Posição PT02", "id_posicao_material": "ID da posição",
            "data_modificacao": "Modificação BINMAT",
        }), width="stretch", hide_index=True)
    else:
        st.info("Verificação BINMAT: 0 materiais com conflito PT02.")

    criticos = preparar_criticos_ressuprimento(radar)
    origens = carregar_saldo_t001_por_posicao(conn)
    retiradas, pendencias = preparar_retiradas_t001(criticos, origens)
    st.caption(
        "Janela móvel da demanda: "
        f"{indicadores['data_inicio_demanda'].strftime('%d/%m/%Y')} a "
        f"{indicadores['data_referencia_demanda'].strftime('%d/%m/%Y')} | "
        f"PT02 analisadas: {indicadores['pt02_definitivas']}"
    )
    st.caption("Crítico: saldo PT02 F5 abaixo de 50% da média mensal. "
               "A sugestão completa 100% da média, limitada ao saldo T001. "
               "Exatamente 50% fica fora. Lista integral, sem Top XX.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Materiais críticos", len(criticos))
    c2.metric("Com retirada planejada", retiradas["material"].nunique())
    c3.metric("Com quantidade pendente", len(pendencias))
    c4.metric("Posições T001 a visitar", retiradas["posicao_t001"].nunique())
    st.caption("Um material com atendimento parcial aparece nas retiradas e nas pendências.")

    st.download_button(
        "Baixar lista completa em Excel (.xlsx)",
        data=gerar_excel_ressuprimento(criticos, retiradas, pendencias, conflitos, indicadores),
        file_name=f"ressuprimento_pt02_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="excel_criticos_ressuprimento_pt02",
    )
    coluna_consulta, _ = st.columns([1, 4])
    with coluna_consulta:
        codigo = st.text_input("Consultar código do material", value="",
            placeholder="Ex.: 1020283", key="consulta_material_ressuprimento_pt02",
            help="Busca exata em todo o radar. Limpe para voltar à lista completa de críticos.").strip()
    if codigo:
        consulta = radar.loc[radar["material"].astype(str).str.strip().eq(codigo)]
        if consulta.empty:
            st.info(f"Material {codigo} não encontrado no radar PT02 atual; "
                    "isso não confirma ausência no cadastro.")
            return
        if consulta["duplicidade_pt02"].any():
            st.error("Consulta com conflito PT02: confira o quadro de posições acima.")
            return
        if not criticos["material"].astype(str).eq(codigo).any():
            st.info("Material fora do corte crítico de 50%. Os valores abaixo são "
                    "do radar geral; não geram retirada nesta lista.")
        for _, item in consulta.iterrows():
            _mostrar_detalhe_material(item)
        retiradas_item = retiradas.loc[retiradas["material"].astype(str).eq(codigo)]
        if not retiradas_item.empty:
            st.subheader("Retiradas deste material")
            st.dataframe(_tabela_exportacao(retiradas_item, COLUNAS_RETIRADAS),
                         width="stretch", hide_index=True)
        pendencias_item = pendencias.loc[pendencias["material"].astype(str).eq(codigo)]
        if not pendencias_item.empty:
            st.dataframe(_tabela_exportacao(pendencias_item, COLUNAS_PENDENCIAS),
                         width="stretch", hide_index=True)
        return

    st.subheader("Retiradas agrupadas por posição T001")
    st.caption("Origens com mais SKUs críticos atendíveis aparecem primeiro. "
               "Cada linha informa a quantidade a retirar naquela origem. "
               "Conferir saldo físico e capacidade da PT02 antes da execução.")
    if retiradas.empty:
        st.info("Nenhuma retirada planejada para os critérios e origens atuais.")
    else:
        st.dataframe(_tabela_exportacao(retiradas, COLUNAS_RETIRADAS),
                     width="stretch", hide_index=True)
    st.subheader("Pendências de abastecimento")
    if pendencias.empty:
        st.info("Nenhuma quantidade pendente entre os materiais críticos.")
    else:
        st.dataframe(_tabela_exportacao(pendencias, COLUNAS_PENDENCIAS),
                     width="stretch", hide_index=True)
    st.subheader("Todos os materiais críticos")
    if criticos.empty:
        st.success("Nenhuma PT02 regular abaixo de 50% da média mensal.")
        return
    evento = st.dataframe(_tabela_exportacao(criticos, COLUNAS_FILA),
        width="stretch", hide_index=True, selection_mode="single-row",
        on_select="rerun", key="criticos_ressuprimento_pt02_v2")
    selecionadas = evento.selection.rows
    if selecionadas and selecionadas[0] < len(criticos):
        _mostrar_detalhe_material(criticos.iloc[selecionadas[0]])
