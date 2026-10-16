# scripts/streamlit_app.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import os
import json
import io
from datetime import datetime
import unicodedata
import re


# =============================================================================
# Helpers de "runtime": evita warning e evita cache quando rodando via "python -c"
# =============================================================================

def _is_streamlit_runtime() -> bool:
    """
    True quando o script está rodando com 'streamlit run'.
    Em import/bare mode (python -c / testes), retorna False.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


def _cache_data(**kwargs):
    """
    Decorator compatível:
      - em runtime Streamlit: usa st.cache_data(...)
      - fora do runtime (import/bare): não faz cache e não gera warnings
    """
    if _is_streamlit_runtime():
        return st.cache_data(**kwargs)

    def deco(fn):
        return fn

    return deco


# =============================================================================
# Config HUB / Paths
# =============================================================================

def hub_config_get(path: str, default=None):
    """
    Lê HUB_CONFIG (JSON) e pega valor por caminho tipo 'estoques.db_path'.
    """
    cfg_path = os.getenv("HUB_CONFIG", "")
    if not cfg_path:
        return default
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cur = cfg
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur
    except Exception:
        return default


# ----------------------------
# Nomes amigáveis (exibição / exportação)
# ----------------------------
COLS_PT = {
    "material": "Material",
    "descricao": "Descrição",
    "quadrante": "Quadrante",

    "delta_val": "Variação de Valor (R$)",
    "delta_qtd": "Variação de Quantidade",
    "qtd_atual": "Saldo atual (qtd)",
    "val_atual": "Saldo atual (R$)",
    "area_negocio": "BU",

    "share_delta_val": "% do Impacto em Valor",
    "cum_share_val": "% Acumulado do Impacto em Valor",

    "share_delta_qtd": "% do Impacto em Quantidade",
    "cum_share_qtd": "% Acumulado do Impacto em Quantidade",

}

# Atenção: sem st.* aqui em cima (pra não executar ao importar)
HUB_ROOT = Path(__file__).resolve().parents[3]  # .../HUB_indicadores

db_rel = hub_config_get(
    "estoques.db_path",
    "data/analiseEstoques/DB/estoque.sqlite",
)

DEFAULT_DB = (HUB_ROOT / db_rel).resolve()

# =============================================================================
# Formatação / normalização
# =============================================================================

def _fmt_ptbr_num(x, nd=2):
    """Formata número no padrão pt-BR: 12.345,67 (sem depender de locale do SO)."""
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        s = f"{float(x):,.{nd}f}"                 # 12,345.67
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return ""


def _fmt_ptbr_int(x):
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return f"{int(round(float(x))):,}".replace(",", ".")
    except Exception:
        return ""


def _fmt_pct(x, nd=2):
    """0.1028 -> 10,28%"""
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return _fmt_ptbr_num(float(x) * 100.0, nd) + "%"
    except Exception:
        return ""


def adicionar_indicador_giro(
    df: pd.DataFrame,
    meta_giro: float,
    coluna_entradas: str = "entradas_val",
    coluna_saldo: str = "saldo_atual_sap_val",
) -> pd.DataFrame:
    """
    Acrescenta o giro mensal e sua situação a uma tabela agregada.

    O cálculo replica o indicador principal do BI:

        giro atual = entradas SAP do mês / saldo atual SAP

    A divisão é feita depois da agregação por BU ou Segmento. Assim, o
    resultado representa a relação entre os totais do grupo, e não uma
    média simples dos giros dos materiais.

    Quando o saldo atual é zero ou negativo, o giro não é calculado para
    evitar uma interpretação artificial de divisão por zero.
    """
    resultado = df.copy()

    entradas = pd.to_numeric(
        resultado[coluna_entradas],
        errors="coerce",
    ).fillna(0.0)

    saldo = pd.to_numeric(
        resultado[coluna_saldo],
        errors="coerce",
    ).fillna(0.0)

    resultado["giro_atual"] = np.nan
    saldo_positivo = saldo > 0
    resultado.loc[saldo_positivo, "giro_atual"] = (
        entradas.loc[saldo_positivo]
        / saldo.loc[saldo_positivo]
    )

    resultado["status_giro"] = np.select(
        [
            resultado["giro_atual"].isna(),
            resultado["giro_atual"] >= float(meta_giro),
        ],
        [
            "⚪ NÃO CALCULADO",
            "🟢 META ATINGIDA",
        ],
        default="🔴 ABAIXO DA META",
    )

    return resultado


def estilizar_indicador_giro(
    df: pd.DataFrame,
    meta_giro: float,
) -> pd.io.formats.style.Styler:
    """Aplica as cores sem alterar os valores usados nos cálculos."""

    def estilo_giro(valor):
        if pd.isna(valor):
            return (
                "background-color: #E5E7EB; "
                "color: #374151; font-weight: 600"
            )

        if float(valor) >= float(meta_giro):
            return (
                "background-color: #D1FAE5; "
                "color: #065F46; font-weight: 700"
            )

        return (
            "background-color: #FEE2E2; "
            "color: #991B1B; font-weight: 700"
        )

    def estilo_status(valor):
        texto = str(valor)

        if "META ATINGIDA" in texto:
            return (
                "background-color: #D1FAE5; "
                "color: #065F46; font-weight: 700"
            )

        if "ABAIXO DA META" in texto:
            return (
                "background-color: #FEE2E2; "
                "color: #991B1B; font-weight: 700"
            )

        return (
            "background-color: #E5E7EB; "
            "color: #374151; font-weight: 600"
        )

    return (
        df.style
        .map(estilo_giro, subset=["Giro atual"])
        .map(estilo_status, subset=["Status giro"])
    )


def df_pt(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renomeia colunas apenas para EXIBIÇÃO/EXPORT.
    Não altera o dataframe original usado em filtros/queries.
    """
    if df is None or df.empty:
        return df
    return df.rename(columns={k: v for k, v in COLS_PT.items() if k in df.columns})


def _norm_txt(x: object) -> str:
    # trata None e NaN (evita "nan" virar opção de filtro)
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""

    s = str(x)

    # normaliza unicode (resolve variações de composição / largura / etc.)
    s = unicodedata.normalize("NFKC", s)

    # remove NBSP e caracteres invisíveis comuns
    s = s.replace("\u00A0", " ")          # NBSP
    s = s.replace("\u200B", "")           # zero width space
    s = s.replace("\u200C", "")           # zero width non-joiner
    s = s.replace("\u200D", "")           # zero width joiner
    s = s.replace("\uFEFF", "")           # BOM / zero width no-break space

    # colapsa whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_bu(x: object) -> str:
    """
    Normalização específica de BU para evitar duplicação visual.
    Padroniza hífens/dashes e espaçamento em volta de '-'.
    """
    s = _norm_txt(x)
    if not s:
        return ""

    # padroniza vários tipos de "hífen/dash" para hífen simples
    s = (s.replace("\u2010", "-")
           .replace("\u2011", "-")
           .replace("\u2012", "-")
           .replace("\u2013", "-")
           .replace("\u2014", "-")
           .replace("\u2212", "-"))

    # padroniza espaços ao redor do hífen
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()

    return s


# =============================================================================
# SQLite read-only (somente leitura)
# =============================================================================

def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """
    Conexão SQLite simples (UNC no Windows OK) + PRAGMA query_only.
    Não usa URI (evita invalid uri authority em caminhos tipo \\SJO-FILE-03\\...).
    """
    con = sqlite3.connect(
        str(db_path),
        timeout=30,
        check_same_thread=False,
    )
    con.execute("PRAGMA query_only = ON;")
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def month_bounds(mes_ref: str) -> tuple[str, str]:
    """('YYYY-MM-01', 'YYYY-MM-01' do mês seguinte)"""
    start = f"{mes_ref}-01"
    next_month = (pd.to_datetime(start) + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d")
    return start, next_month


def build_excel_export(
    df_pareto_det: pd.DataFrame,
    df_resumo: pd.DataFrame,
    params: dict,
) -> bytes:
    """Gera XLSX em memória para st.download_button."""
    output = io.BytesIO()

    det = df_pareto_det.copy()
    res = df_resumo.copy()

    # nomes amigáveis (português) só para exportação
    det = df_pt(det)
    res = df_pt(res)

    # aba de parâmetros
    df_params = pd.DataFrame([{"chave": k, "valor": v} for k, v in params.items()])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        det.to_excel(writer, sheet_name="PARETO_DETALHE", index=False)
        res.to_excel(writer, sheet_name="RESUMO_QUADRANTES", index=False)
        df_params.to_excel(writer, sheet_name="PARAMETROS", index=False)

        for sheet in ["PARETO_DETALHE", "RESUMO_QUADRANTES", "PARAMETROS"]:
            ws = writer.book[sheet]
            ws.freeze_panes = "A2"

    return output.getvalue()


# =============================================================================
# Queries (cache só em runtime)
# =============================================================================

@_cache_data(ttl=120)
def load_kpi_mensal_mast(
    db_path_str: str,
    mes_ref: str,
    meta_giro: float,
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    db_path = Path(db_path_str)
    start, next_month = month_bounds(mes_ref)

    filtro_movimento = ""

    if desconsiderar_mov_343_344:
        filtro_movimento = """
          AND TRIM(COALESCE(tipo_movimento, '')) NOT IN ('343', '344')
        """

    with connect_readonly(db_path) as con:
        b = con.execute("""
            SELECT baseline_date, qtd_base_total, val_base_total
            FROM baseline_mensal
            WHERE mes_ref=? AND deposito='MAST';
        """, (mes_ref,)).fetchone()

        if not b:
            return pd.DataFrame()

        baseline_date, qtd_base, val_base = b

        last_snap = con.execute("""
            SELECT MAX(snapshot_date)
            FROM fact_estoque_snapshot
            WHERE deposito='MAST'
              AND snapshot_date >= ?
              AND snapshot_date < ?;
        """, (start, next_month)).fetchone()[0]

        if not last_snap:
            return pd.DataFrame()

        qtd_atual, val_atual = con.execute("""
            SELECT
              COALESCE(SUM(qtd_total), 0),
              COALESCE(SUM(val_total), 0)
            FROM fact_estoque_snapshot
            WHERE deposito='MAST'
              AND snapshot_date=?;
        """, (last_snap,)).fetchone()

        qtd_atual = float(qtd_atual or 0)
        val_atual = float(val_atual or 0)

        mb = con.execute(f"""
            SELECT
              COALESCE(SUM(CASE
                    WHEN deb_cred='S'
                     AND TRIM(COALESCE(ordem, ''))=''
                    THEN quantidade
                    ELSE 0
              END), 0) AS entradas_qtd,

              COALESCE(SUM(CASE
                    WHEN deb_cred='S'
                     AND TRIM(COALESCE(ordem, ''))=''
                    THEN valor_estimado
                    ELSE 0
              END), 0) AS entradas_val,

              COALESCE(SUM(CASE
                    WHEN deb_cred='H'
                    THEN quantidade
                    ELSE 0
              END), 0) AS saidas_qtd,

              COALESCE(SUM(CASE
                    WHEN deb_cred='H'
                    THEN valor_estimado
                    ELSE 0
              END), 0) AS saidas_val

            FROM fact_mb51_mov
            WHERE deposito='MAST'
              {filtro_movimento}
              AND data_lancamento >= ?
              AND data_lancamento < ?;
        """, (start, next_month)).fetchone()

        entradas_qtd, entradas_val, saidas_qtd, saidas_val = [
            float(x or 0) for x in mb
        ]

        giro_operacional_val = (
            saidas_val / val_base
            if val_base not in (None, 0)
            else None
        )

        giro_operacional_qtd = (
            saidas_qtd / qtd_base
            if qtd_base not in (None, 0)
            else None
        )

        meta_saldo_val = (
            val_base / meta_giro
            if val_base not in (None, 0)
            and meta_giro not in (None, 0)
            else None
        )

        meta_saldo_qtd = (
            qtd_base / meta_giro
            if qtd_base not in (None, 0)
            and meta_giro not in (None, 0)
            else None
        )

        falta_baixar_val = (
            val_atual - meta_saldo_val
            if meta_saldo_val is not None
            else None
        )

        falta_baixar_qtd = (
            qtd_atual - meta_saldo_qtd
            if meta_saldo_qtd is not None
            else None
        )

        ating_meta_giro_val = (
            giro_operacional_val / meta_giro
            if giro_operacional_val is not None
            and meta_giro not in (None, 0)
            else None
        )

        ating_meta_giro_qtd = (
            giro_operacional_qtd / meta_giro
            if giro_operacional_qtd is not None
            and meta_giro not in (None, 0)
            else None
        )

        giro_bi_val = (
            entradas_val / val_atual
            if val_atual not in (None, 0)
            else None
        )

        giro_bi_qtd = (
            entradas_qtd / qtd_atual
            if qtd_atual not in (None, 0)
            else None
        )

        meta_saldo_bi_val = (
            entradas_val / meta_giro
            if entradas_val not in (None, 0)
            and meta_giro not in (None, 0)
            else None
        )

        meta_saldo_bi_qtd = (
            entradas_qtd / meta_giro
            if entradas_qtd not in (None, 0)
            and meta_giro not in (None, 0)
            else None
        )

        saldo_a_baixar_bi_val = (
            val_atual - meta_saldo_bi_val
            if meta_saldo_bi_val is not None
            else None
        )

        saldo_a_baixar_bi_qtd = (
            qtd_atual - meta_saldo_bi_qtd
            if meta_saldo_bi_qtd is not None
            else None
        )

        consumo_liq_qtd = saidas_qtd - entradas_qtd
        consumo_liq_val = saidas_val - entradas_val

        eficiencia_val = (
            saidas_val / entradas_val
            if entradas_val not in (None, 0)
            else None
        )

        eficiencia_qtd = (
            saidas_qtd / entradas_qtd
            if entradas_qtd not in (None, 0)
            else None
        )

    return pd.DataFrame([{
        "mes_ref": mes_ref,
        "meta_giro": float(meta_giro),
        "baseline_date": str(baseline_date),
        "val_base_total": float(val_base or 0),
        "qtd_base_total": float(qtd_base or 0),
        "last_snapshot_date": str(last_snap),
        "val_atual_total": round(val_atual, 2),

        "giro_bi_val": (
            None
            if giro_bi_val is None
            else round(float(giro_bi_val), 4)
        ),
        "giro_bi_qtd": (
            None
            if giro_bi_qtd is None
            else round(float(giro_bi_qtd), 4)
        ),
        "meta_saldo_bi_val": (
            None
            if meta_saldo_bi_val is None
            else round(float(meta_saldo_bi_val), 2)
        ),
        "meta_saldo_bi_qtd": (
            None
            if meta_saldo_bi_qtd is None
            else round(float(meta_saldo_bi_qtd), 3)
        ),
        "saldo_a_baixar_bi_val": (
            None
            if saldo_a_baixar_bi_val is None
            else round(float(saldo_a_baixar_bi_val), 2)
        ),
        "saldo_a_baixar_bi_qtd": (
            None
            if saldo_a_baixar_bi_qtd is None
            else round(float(saldo_a_baixar_bi_qtd), 3)
        ),

        "qtd_atual_total": round(qtd_atual, 3),
        "giro_operacional_val": (
            None
            if giro_operacional_val is None
            else round(float(giro_operacional_val), 4)
        ),
        "giro_operacional_qtd": (
            None
            if giro_operacional_qtd is None
            else round(float(giro_operacional_qtd), 4)
        ),
        "ating_meta_giro_val": (
            None
            if ating_meta_giro_val is None
            else round(float(ating_meta_giro_val), 4)
        ),
        "ating_meta_giro_qtd": (
            None
            if ating_meta_giro_qtd is None
            else round(float(ating_meta_giro_qtd), 4)
        ),
        "meta_saldo_val": (
            None
            if meta_saldo_val is None
            else round(float(meta_saldo_val), 2)
        ),
        "meta_saldo_qtd": (
            None
            if meta_saldo_qtd is None
            else round(float(meta_saldo_qtd), 3)
        ),
        "falta_baixar_val": (
            None
            if falta_baixar_val is None
            else round(float(falta_baixar_val), 2)
        ),
        "falta_baixar_qtd": (
            None
            if falta_baixar_qtd is None
            else round(float(falta_baixar_qtd), 3)
        ),

        "entradas_reais_qtd_mes": round(entradas_qtd, 3),
        "entradas_reais_val_mes": round(entradas_val, 2),
        "saidas_reais_qtd_mes": round(saidas_qtd, 3),
        "saidas_reais_val_mes": round(saidas_val, 2),
        "consumo_liq_qtd_mes": round(consumo_liq_qtd, 3),
        "consumo_liq_val_mes": round(consumo_liq_val, 2),
        "eficiencia_val_ratio": (
            None
            if eficiencia_val is None
            else round(float(eficiencia_val), 4)
        ),
        "eficiencia_qtd_ratio": (
            None
            if eficiencia_qtd is None
            else round(float(eficiencia_qtd), 4)
        ),
    }])

@_cache_data(ttl=120)
def _load_eficiencia_hierarquia_mast(
    db_path_str: str,
    mes_ref: str,
    group_fields: list[str],
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    """
    Calcula a eficiência financeira do MAST por hierarquia comercial.

    Fontes utilizadas:
    - baseline e saldo atual: fact_estoque_snapshot;
    - entradas reais: MB51 com débito/crédito = 'S' e ordem vazia;
    - saídas reais: todos os movimentos MB51 com débito/crédito = 'H';
    - hierarquia comercial: dim_material.

    O baseline representa a fotografia de referência do saldo do mês.

    As movimentações MB51 são apuradas pelo mês calendário completo
    (do primeiro dia do mês até o início do mês seguinte), independentemente
    da data em que o snapshot de baseline foi registrado. Isso preserva
    o ciclo operacional mensal mesmo quando a baseline é criada após
    o primeiro dia do mês.

    O filtro opcional 343/344 segue a mesma regra usada nos demais
    indicadores MB51 do dashboard.
    """

    campos_validos = {
        "bu",
        "diretoria",
        "segmento",
        "centro_lucro",
        "centro_custo",
    }

    if not group_fields:
        raise ValueError(
            "Informe pelo menos um campo de agrupamento."
        )

    campos_invalidos = set(group_fields) - campos_validos

    if campos_invalidos:
        raise ValueError(
            f"Campos de agrupamento inválidos: "
            f"{sorted(campos_invalidos)}"
        )

    db_path = Path(db_path_str)
    start, next_month = month_bounds(mes_ref)

    filtro_movimento = ""

    if desconsiderar_mov_343_344:
        filtro_movimento = """
          AND TRIM(COALESCE(tipo_movimento, ''))
              NOT IN ('343', '344')
        """

    with connect_readonly(db_path) as con:
        # ------------------------------------------------------------
        # 1) Descobre a fotografia inicial do ciclo.
        # ------------------------------------------------------------
        row_base = con.execute(
            """
            SELECT baseline_date
            FROM baseline_mensal
            WHERE mes_ref = ?
              AND deposito = 'MAST'
            """,
            (mes_ref,),
        ).fetchone()

        if not row_base:
            return pd.DataFrame()

        baseline_date = row_base[0]

        # ------------------------------------------------------------
        # 2) Descobre o snapshot mais recente disponível no mês.
        # ------------------------------------------------------------
        last_snap = con.execute(
            """
            SELECT MAX(snapshot_date)
            FROM fact_estoque_snapshot
            WHERE deposito = 'MAST'
              AND snapshot_date >= ?
              AND snapshot_date < ?
            """,
            (baseline_date, next_month),
        ).fetchone()[0]

        if not last_snap:
            return pd.DataFrame()

        # ------------------------------------------------------------
        # 3) Baseline por material.
        # ------------------------------------------------------------
        df_base = pd.read_sql_query(
            """
            SELECT
                material,
                SUM(COALESCE(val_total, 0)) AS baseline_val
            FROM fact_estoque_snapshot
            WHERE deposito = 'MAST'
              AND snapshot_date = ?
            GROUP BY material
            """,
            con,
            params=[baseline_date],
        )

        # ------------------------------------------------------------
        # 4) Saldo atual por material.
        # ------------------------------------------------------------
        df_atual = pd.read_sql_query(
            """
            SELECT
                material,
                SUM(COALESCE(val_total, 0)) AS saldo_atual_sap_val
            FROM fact_estoque_snapshot
            WHERE deposito = 'MAST'
              AND snapshot_date = ?
            GROUP BY material
            """,
            con,
            params=[last_snap],
        )

        # ------------------------------------------------------------
        # 5) Movimentos reais MB51 por material.
        #
        # Entrada real:
        #   S + ordem vazia.
        #
        # Saída real:
        #   todo H, independentemente de ordem.
        # ------------------------------------------------------------
        df_mov = pd.read_sql_query(
            f"""
            SELECT
                material,

                SUM(
                    CASE
                        WHEN deb_cred = 'S'
                         AND TRIM(COALESCE(ordem, '')) = ''
                        THEN COALESCE(valor_estimado, 0)
                        ELSE 0
                    END
                ) AS entradas_val,

                SUM(
                    CASE
                        WHEN deb_cred = 'H'
                        THEN COALESCE(valor_estimado, 0)
                        ELSE 0
                    END
                ) AS consumo_real_sap_val

            FROM fact_mb51_mov

            WHERE deposito = 'MAST'
              AND data_lancamento >= ?
              AND data_lancamento < ?
              {filtro_movimento}

            GROUP BY material
            """,
            con,
            params=[
                start,
                next_month,
            ],
        )

        # ------------------------------------------------------------
        # 6) Hierarquia comercial oficial por material.
        # ------------------------------------------------------------
        df_dim = pd.read_sql_query(
            """
            SELECT
                material,
                bu,
                diretoria,
                segmento,
                centro_lucro,
                centro_custo
            FROM dim_material
            """,
            con,
        )

    # ------------------------------------------------------------
    # 7) Consolida posição + movimentação no nível material.
    # ------------------------------------------------------------
    df_calc = (
        df_base
        .merge(
            df_atual,
            on="material",
            how="outer",
        )
        .merge(
            df_mov,
            on="material",
            how="outer",
        )
        .merge(
            df_dim,
            on="material",
            how="left",
        )
    )

    if df_calc.empty:
        return pd.DataFrame()

    # ------------------------------------------------------------
    # 8) Valores ausentes significam ausência daquele componente
    # para o material no período.
    # ------------------------------------------------------------
    colunas_valor = [
        "baseline_val",
        "entradas_val",
        "consumo_real_sap_val",
        "saldo_atual_sap_val",
    ]

    for coluna in colunas_valor:
        df_calc[coluna] = pd.to_numeric(
            df_calc[coluna],
            errors="coerce",
        ).fillna(0.0)

    # ------------------------------------------------------------
    # 9) Materiais sem classificação continuam visíveis.
    # Isso permite auditar eventual perda de cobertura da dimensão.
    # ------------------------------------------------------------
    for campo in group_fields:
        df_calc[campo] = (
            df_calc[campo]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        df_calc.loc[
            df_calc[campo] == "",
            campo,
        ] = f"SEM_{campo.upper()}"

    # ------------------------------------------------------------
    # 10) Agrega na hierarquia solicitada:
    # BU, BU/Diretoria, BU/Diretoria/Segmento etc.
    # ------------------------------------------------------------
    df = (
        df_calc.groupby(
            group_fields,
            as_index=False,
        )
        .agg(
            baseline_val=("baseline_val", "sum"),
            entradas_val=("entradas_val", "sum"),
            consumo_real_sap_val=(
                "consumo_real_sap_val",
                "sum",
            ),
            saldo_atual_sap_val=(
                "saldo_atual_sap_val",
                "sum",
            ),
        )
    )

    # ------------------------------------------------------------
    # 11) Base disponível no ciclo.
    # ------------------------------------------------------------
    df["base_disponivel_val"] = (
        df["baseline_val"]
        + df["entradas_val"]
    )

    # ------------------------------------------------------------
    # 12) Eficiência:
    # consumo real / base disponível.
    # ------------------------------------------------------------
    df["eficiencia_disponibilidade_pct"] = np.where(
        df["base_disponivel_val"] > 0,
        (
            df["consumo_real_sap_val"]
            / df["base_disponivel_val"]
        ),
        0,
    )

    # Mantém os nomes esperados pela interface atual.
    df["saidas_val"] = df["consumo_real_sap_val"]

    df["eficiencia_pct"] = (
        df["eficiencia_disponibilidade_pct"]
    )

    df["baseline_restante"] = (
        df["saldo_atual_sap_val"]
    )

    # ------------------------------------------------------------
    # 13) Participação no consumo real.
    # ------------------------------------------------------------
    total_consumo = float(
        df["consumo_real_sap_val"].sum()
    )

    df["participacao_saida_pct"] = np.where(
        total_consumo > 0,
        df["consumo_real_sap_val"] / total_consumo,
        0,
    )

    # ------------------------------------------------------------
    # 14) Participação no baseline.
    # ------------------------------------------------------------
    total_baseline = float(
        df["baseline_val"].sum()
    )

    df["participacao_baseline_pct"] = np.where(
        total_baseline > 0,
        df["baseline_val"] / total_baseline,
        0,
    )

    df["classe_relevancia"] = np.where(
        df["participacao_baseline_pct"] >= 0.03,
        "Relevante",
        "Baixo impacto",
    )

    # Datas usadas para auditoria da tela.
    df["baseline_date"] = baseline_date
    df["last_snapshot_date"] = last_snap

    df = df.sort_values(
        "consumo_real_sap_val",
        ascending=False,
    ).reset_index(drop=True)

    return df

@_cache_data(ttl=120)
def load_eficiencia_bu_mast(
    db_path_str: str,
    mes_ref: str,
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    df = _load_eficiencia_hierarquia_mast(
        db_path_str=db_path_str,
        mes_ref=mes_ref,
        group_fields=["bu"],
        desconsiderar_mov_343_344=desconsiderar_mov_343_344,
    )

    if not df.empty:
        df["area_negocio"] = df["bu"]

    return df


@_cache_data(ttl=120)
def load_eficiencia_segmento_mast(
    db_path_str: str,
    mes_ref: str,
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    return _load_eficiencia_hierarquia_mast(
        db_path_str=db_path_str,
        mes_ref=mes_ref,
        group_fields=[
            "bu",
            "diretoria",
            "segmento",
        ],
        desconsiderar_mov_343_344=desconsiderar_mov_343_344,
    )

@_cache_data(ttl=120)
def load_snapshot_saldo_mes(db_path_str: str, mes_ref: str) -> pd.DataFrame:
    db_path = Path(db_path_str)
    start, next_month = month_bounds(mes_ref)
    with connect_readonly(db_path) as con:
        return pd.read_sql_query("""
            SELECT
              snapshot_date AS dia,
              COALESCE(SUM(val_total),0) AS saldo_val,
              COALESCE(SUM(qtd_total),0) AS saldo_qtd
            FROM fact_estoque_snapshot
            WHERE deposito='MAST'
              AND snapshot_date >= ?
              AND snapshot_date <  ?
            GROUP BY snapshot_date
            ORDER BY snapshot_date;
        """, con, params=[start, next_month])

@_cache_data(ttl=120)
def load_mb51_diario_real_mes(
    db_path_str: str,
    mes_ref: str,
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    """
    MB51 REAL diário (MAST) no mês.
    Entradas reais: S e ordem vazia.
    Saídas reais: H, todas, independentemente de ordem.
    """
    db_path = Path(db_path_str)
    start, next_month = month_bounds(mes_ref)

    filtro_movimento = ""

    if desconsiderar_mov_343_344:
        filtro_movimento = """
          AND TRIM(COALESCE(tipo_movimento,'')) NOT IN ('343','344')
        """

    with connect_readonly(db_path) as con:
        df = pd.read_sql_query(
            f"""
            SELECT
              data_lancamento AS dia,
              SUM(
                  CASE
                      WHEN deb_cred='S'
                       AND TRIM(COALESCE(ordem,''))=''
                      THEN quantidade
                      ELSE 0
                  END
              ) AS entradas_qtd,
              SUM(
                  CASE
                      WHEN deb_cred='S'
                       AND TRIM(COALESCE(ordem,''))=''
                      THEN valor_estimado
                      ELSE 0
                  END
              ) AS entradas_val,
              SUM(
                  CASE
                      WHEN deb_cred='H'
                      THEN quantidade
                      ELSE 0
                  END
              ) AS saidas_qtd,
              SUM(
                  CASE
                      WHEN deb_cred='H'
                      THEN valor_estimado
                      ELSE 0
                  END
              ) AS saidas_val
            FROM fact_mb51_mov
            WHERE deposito='MAST'
              AND data_lancamento >= ?
              AND data_lancamento < ?
              {filtro_movimento}
            GROUP BY data_lancamento
            ORDER BY data_lancamento;
            """,
            con,
            params=[start, next_month],
        )

    if df.empty:
        return df

    df["consumo_liq_qtd"] = df["saidas_qtd"] - df["entradas_qtd"]
    df["consumo_liq_val"] = df["saidas_val"] - df["entradas_val"]

    return df

@_cache_data(ttl=120)
def load_ataque_quadrantes_mes(db_path_str: str, mes_ref: str, p: float = 0.70) -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    db_path = Path(db_path_str)
    start, next_month = month_bounds(mes_ref)

    with connect_readonly(db_path) as con:
        b = con.execute("""
            SELECT baseline_date
            FROM baseline_mensal
            WHERE mes_ref=? AND deposito='MAST';
        """, (mes_ref,)).fetchone()
        if not b:
            return pd.DataFrame(), pd.DataFrame(), 0.0, 0.0

        baseline_date = b[0]

        last_snap = con.execute("""
            SELECT MAX(snapshot_date)
            FROM fact_estoque_snapshot
            WHERE deposito='MAST'
              AND snapshot_date >= ?
              AND snapshot_date <  ?;
        """, (start, next_month)).fetchone()[0]

        if not last_snap:
            return pd.DataFrame(), pd.DataFrame(), 0.0, 0.0

        df_base = pd.read_sql_query("""
            SELECT material,
                   COALESCE(descricao,'') AS descricao,
                   COALESCE(qtd_total,0) AS qtd_base,
                   COALESCE(val_total,0) AS val_base
            FROM fact_estoque_snapshot
            WHERE deposito='MAST' AND snapshot_date=?;
        """, con, params=[baseline_date])

        df_atual = pd.read_sql_query("""
            SELECT material,
                   COALESCE(descricao,'') AS descricao,
                   COALESCE(qtd_total,0) AS qtd_atual,
                   COALESCE(val_total,0) AS val_atual
            FROM fact_estoque_snapshot
            WHERE deposito='MAST' AND snapshot_date=?;
        """, con, params=[last_snap])

        # ------------------------------------------------------------
        # Dimensão oficial de materiais.
        #
        # A estrutura comercial atual é:
        # BU -> Diretoria -> Segmento.
        #
        # O processamento também vem da dim_material, consolidado
        # a partir da fonte oficial definida no ETL.
        # ------------------------------------------------------------
        d_material = pd.read_sql_query(
            """
            SELECT
                material,
                bu,
                diretoria,
                segmento,
                processamento
            FROM dim_material;
            """,
            con,
        )

    df = df_base.merge(df_atual, on="material", how="outer", suffixes=("_base", "_atual"))

    df["descricao"] = df["descricao_atual"].fillna("").astype(str)
    mask_desc_vazia = df["descricao"].str.strip().eq("")
    df.loc[mask_desc_vazia, "descricao"] = df.loc[mask_desc_vazia, "descricao_base"].fillna("").astype(str)

    for col in ["qtd_base", "val_base", "qtd_atual", "val_atual"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["delta_qtd"] = df["qtd_atual"] - df["qtd_base"]
    df["delta_val"] = df["val_atual"] - df["val_base"]

    pos_val = df.loc[df["delta_val"] > 0, "delta_val"]
    pos_qtd = df.loc[df["delta_qtd"] > 0, "delta_qtd"]

    cut_val = float(pos_val.quantile(p)) if not pos_val.empty else 0.0
    cut_qtd = float(pos_qtd.quantile(p)) if not pos_qtd.empty else 0.0

    alto_val = (df["delta_val"] > 0) & (df["delta_val"] >= cut_val)
    alta_qtd = (df["delta_qtd"] > 0) & (df["delta_qtd"] >= cut_qtd)

    def _quad(av, aq):
        if av and aq:
            return "Q1_ALTO_VALOR_ALTA_QTD"
        if av and (not aq):
            return "Q2_ALTO_VALOR"
        if (not av) and aq:
            return "Q3_ALTA_QTD"
        return "Q4_ESTAVEL_OU_REDUCAO"

    df["quadrante"] = [_quad(av, aq) for av, aq in zip(alto_val.tolist(), alta_qtd.tolist())]

    # Acrescenta a hierarquia comercial e o processamento oficiais.
    # O LEFT JOIN preserva materiais do estoque mesmo quando ainda
    # não houver classificação correspondente na dim_material.
    df = df.merge(
        d_material,
        on="material",
        how="left",
    )

    df["mes_ref"] = mes_ref

    df_det = df.sort_values(["quadrante", "delta_val", "delta_qtd"], ascending=[True, False, False]).reset_index(drop=True)

    df_resumo = (
        df_det.groupby(["mes_ref", "quadrante"], as_index=False)
              .agg(
                  qt_materiais=("material", "count"),
                  soma_delta_val=("delta_val", "sum"),
                  soma_delta_qtd=("delta_qtd", "sum"),
              )
              .sort_values("quadrante")
              .reset_index(drop=True)
    )

    return df_resumo, df_det, cut_val, cut_qtd


@_cache_data(ttl=120)
def list_meses_disponiveis(db_path_str: str) -> list[str]:
    db_path = Path(db_path_str)
    with connect_readonly(db_path) as con:
        rows = con.execute("""
            SELECT DISTINCT mes_ref
            FROM baseline_mensal
            WHERE deposito='MAST'
            ORDER BY mes_ref;
        """).fetchall()
    return [r[0] for r in rows]


@_cache_data(ttl=120)
def load_evolucao_mensal_mast(
    db_path_str: str,
    meses_ref: tuple[str, ...],
    desconsiderar_mov_343_344: bool = False,
) -> pd.DataFrame:
    """
    Carrega a evolução financeira mensal do depósito MAST.

    Para cada mês solicitado, retorna:
    - entradas financeiras apuradas na MB51;
    - saldo do último snapshot disponível no mês;
    - giro do BI, calculado como entradas divididas pelo saldo.

    A consulta foi consolidada para percorrer cada tabela somente uma vez
    no período selecionado. Isso evita repetir consultas pesadas para cada
    mês, principalmente quando o banco está armazenado na rede.
    """

    colunas = [
        "mes_ref",
        "snapshot_date",
        "entradas_val",
        "saldo_val",
        "giro",
    ]

    if not meses_ref:
        return pd.DataFrame(columns=colunas)

    db_path = Path(db_path_str)

    # Remove eventuais duplicidades e garante ordem cronológica.
    meses_ordenados = tuple(sorted(set(meses_ref)))

    # Os períodos usados pela interface são contínuos. Por isso, basta
    # consultar do início do primeiro mês ao início do mês posterior ao último.
    inicio_periodo = month_bounds(meses_ordenados[0])[0]
    fim_periodo = month_bounds(meses_ordenados[-1])[1]

    filtro_movimento = ""

    if desconsiderar_mov_343_344:
        filtro_movimento = """
          AND TRIM(COALESCE(tipo_movimento, '')) NOT IN ('343', '344')
        """

    with connect_readonly(db_path) as con:
        # ------------------------------------------------------------
        # 1) Saldos mensais
        # ------------------------------------------------------------
        # Primeiro identifica o último snapshot de cada mês. Em seguida,
        # soma todas as linhas pertencentes àquela fotografia.
        #
        # A tabela de snapshots é percorrida uma única vez no período,
        # em vez de duas vezes para cada mês.
        saldos_rows = con.execute(
            """
            WITH ultimos_snapshots AS (
                SELECT
                    SUBSTR(snapshot_date, 1, 7) AS mes_ref,
                    MAX(snapshot_date) AS snapshot_date
                FROM fact_estoque_snapshot
                WHERE deposito = 'MAST'
                  AND snapshot_date >= ?
                  AND snapshot_date < ?
                GROUP BY SUBSTR(snapshot_date, 1, 7)
            )
            SELECT
                ultimos.mes_ref,
                ultimos.snapshot_date,
                COALESCE(SUM(snapshot.val_total), 0) AS saldo_val
            FROM ultimos_snapshots AS ultimos
            INNER JOIN fact_estoque_snapshot AS snapshot
                ON snapshot.deposito = 'MAST'
               AND snapshot.snapshot_date = ultimos.snapshot_date
            GROUP BY
                ultimos.mes_ref,
                ultimos.snapshot_date
            ORDER BY
                ultimos.mes_ref;
            """,
            (inicio_periodo, fim_periodo),
        ).fetchall()

        # ------------------------------------------------------------
        # 2) Entradas mensais
        # ------------------------------------------------------------
        # Regra homologada do BI:
        # - débito/crédito igual a "S";
        # - ordem vazia;
        # - filtro opcional dos movimentos 343 e 344.
        #
        # Toda a MB51 do período é agregada em uma única consulta.
        entradas_rows = con.execute(
            f"""
            SELECT
                SUBSTR(data_lancamento, 1, 7) AS mes_ref,
                COALESCE(
                    SUM(valor_estimado),
                    0
                ) AS entradas_val
            FROM fact_mb51_mov
            WHERE deposito = 'MAST'
              AND deb_cred = 'S'
              AND TRIM(COALESCE(ordem, '')) = ''
              {filtro_movimento}
              AND data_lancamento >= ?
              AND data_lancamento < ?
            GROUP BY SUBSTR(data_lancamento, 1, 7)
            ORDER BY mes_ref;
            """,
            (inicio_periodo, fim_periodo),
        ).fetchall()

    # Dicionários permitem combinar rapidamente as duas consultas pelo mês.
    saldos_por_mes = {
        str(mes): {
            "snapshot_date": str(snapshot_date),
            "saldo_val": float(saldo_val or 0),
        }
        for mes, snapshot_date, saldo_val in saldos_rows
    }

    entradas_por_mes = {
        str(mes): float(entradas_val or 0)
        for mes, entradas_val in entradas_rows
    }

    registros: list[dict] = []

    for mes_ref in meses_ordenados:
        saldo_mes = saldos_por_mes.get(mes_ref)

        # Sem snapshot não existe saldo confiável nem giro para o mês.
        if saldo_mes is None:
            continue

        saldo_val = float(saldo_mes["saldo_val"])
        entradas_val = float(entradas_por_mes.get(mes_ref, 0.0))

        giro = (
            entradas_val / saldo_val
            if saldo_val != 0
            else None
        )

        registros.append(
            {
                "mes_ref": mes_ref,
                "snapshot_date": saldo_mes["snapshot_date"],
                "entradas_val": round(entradas_val, 2),
                "saldo_val": round(saldo_val, 2),
                "giro": (
                    None
                    if giro is None
                    else round(float(giro), 4)
                ),
            }
        )

    return pd.DataFrame(
        registros,
        columns=colunas,
    ).reset_index(drop=True)

# =============================================================================
# APP (tudo que usa st.* fica aqui dentro)
# =============================================================================

def run():
    # ----------------------------
    # Config do App (somente aqui dentro)
    # ----------------------------
    st.set_page_config(page_title="Analise Estoques - MAST", layout="wide")
    st.title("Analise Estoques - MAST (SQLite)")
    st.caption("Fonte: SQLite (somente leitura). KPI mensal = snapshot (saldo/meta/giro) + MB51 REAL (eficiência).")

    # ----------------------------
    # Sidebar
    # ----------------------------
    st.sidebar.header("Parâmetros")

    # O caminho do banco é definido internamente pela configuração do HUB.
    # Não deve ser exibido nem editado pela interface do operador.
    db_path = str(DEFAULT_DB)

    meta_giro = st.sidebar.number_input(
        "Meta de giro (mês)",
        min_value=0.1,
        max_value=10.0,
        value=1.2,
        step=0.1,
    )

    # ------------------------------------------------------------------
    # Filtro opcional para análises operacionais
    #
    # Quando marcado, os movimentos SAP 343 e 344 (bloqueio/desbloqueio)
    # serão desconsiderados nas consultas MB51.
    #
    # Nesta primeira etapa o checkbox apenas cria a variável.
    # Nenhuma consulta utiliza este valor ainda.
    # ------------------------------------------------------------------
    desconsiderar_mov_343_344 = st.sidebar.checkbox(
        "Desconsiderar movimentos 343 e 344",
        value=True,
        help=(
            "Remove das análises MB51 os movimentos de bloqueio/desbloqueio "
            "(343 e 344). O comportamento padrão permanece inalterado."
        ),
    )

    meses = list_meses_disponiveis(db_path)

    if not meses:
        st.error(
            "Não encontrei meses em baseline_mensal para MAST. "
            "Rode o ETL primeiro."
        )
        st.stop()

    mes_ref = st.sidebar.selectbox(
        "Mês de referência",
        options=meses,
        index=len(meses) - 1,
    )

    # ----------------------------
    # Tabs
    # ----------------------------
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "Mensal (KPI)",
            "Diário (séries)",
            "Ataque (quadrantes)",
            "Evolução mensal",
        ]
    )

    with tab1:
        kpi = load_kpi_mensal_mast(
        db_path,
        mes_ref,
        float(meta_giro),
        desconsiderar_mov_343_344,
    )
        if kpi.empty:
            st.error(f"Sem dados suficientes para montar o KPI mensal de {mes_ref}.")
            st.stop()

        row = kpi.iloc[0].to_dict()

        st.markdown("### BI (replicado)")

        entradas_bi = row.get("entradas_reais_val_mes", 0.0)
        saldo_bi    = row.get("val_atual_total", None)

        meta_saldo_bi = row.get("meta_saldo_bi_val", None)
        saldo_a_baixar_bi = row.get("saldo_a_baixar_bi_val", None)
        giro_bi = row.get("giro_bi_val", None)

        b1, b2, b3, b4, b5 = st.columns(5)
        b1.metric("Entradas MAST (R$)", f"{entradas_bi:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        b2.metric("Saldo MAST (R$)", f"{saldo_bi:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if saldo_bi is not None else "NA")
        b3.metric("Meta de saldo (R$)", f"{meta_saldo_bi:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if meta_saldo_bi is not None else "NA")
        b4.metric("Saldo a baixar (R$)", f"{saldo_a_baixar_bi:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if saldo_a_baixar_bi is not None else "NA")
        b5.metric("Giro atual (mês)", f"{giro_bi:.2f}" if giro_bi is not None else "NA")

        st.info(
            "📌 **BI (replicado):** Entradas do mês (S + ORDEM vazia) comparadas com o **saldo atual (snapshot)** "
            "para obter Giro Atual, Meta de Saldo e Saldo a Baixar (mesma lógica do BI corporativo)."
        )

        st.divider()

        st.markdown("### Eficiência (Consumo do Baseline)")

        baseline_val = row.get("val_base_total", None)
        saidas_val_mes = row.get("saidas_reais_val_mes", None)

        if baseline_val not in (None, 0) and saidas_val_mes is not None:
            eficiencia_baseline = float(saidas_val_mes) / float(baseline_val)
            baseline_restante = max(0.0, float(baseline_val) - float(saidas_val_mes))
            eficiencia_extra = max(0.0, float(saidas_val_mes) - float(baseline_val))
        else:
            eficiencia_baseline = None
            baseline_restante = None
            eficiencia_extra = None

        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Baseline inicial (R$)", f"{baseline_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if baseline_val is not None else "NA")
        e2.metric("Saídas no mês (R$)", f"{saidas_val_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if saidas_val_mes is not None else "NA")
        e3.metric("Baseline restante (R$)", f"{baseline_restante:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if baseline_restante is not None else "NA")
        e4.metric("Eficiência vs baseline", f"{(eficiencia_baseline*100):.1f}%" if eficiencia_baseline is not None else "NA")
        e5.metric("Eficiência extra (R$)", f"{eficiencia_extra:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if eficiencia_extra is not None else "0,00")

        st.info(
            "📌 **Eficiência (baseline):** mede o quanto do saldo inicial do mês já foi consumido via saídas. "
            "Se as saídas ultrapassarem o baseline, o excedente é mostrado como **eficiência extra** (consumo do que entrou no mês)."
        )

        st.markdown("### Eficiência por BU")

        df_bu = load_eficiencia_bu_mast(
            db_path,
            mes_ref,
            desconsiderar_mov_343_344,
        )

        if df_bu.empty:
            st.info("Sem dados suficientes para calcular eficiência por BU.")
        else:
            df_bu_view = adicionar_indicador_giro(
                df_bu,
                meta_giro=float(meta_giro),
            )

            df_bu_view["Baseline inicial (R$)"] = df_bu_view["baseline_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Saídas MB51 (R$)"] = df_bu_view["saidas_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Consumo real SAP (R$)"] = df_bu_view["consumo_real_sap_val"].map(
                lambda x: _fmt_ptbr_num(x, 2)
            )
            df_bu_view["Baseline inicial (R$)"] = df_bu_view["baseline_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Entradas SAP (R$)"] = df_bu_view["entradas_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Base disponível (R$)"] = df_bu_view["base_disponivel_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Consumo SAP (R$)"] = df_bu_view["consumo_real_sap_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Saldo atual (SAP) (R$)"] = df_bu_view["saldo_atual_sap_val"].map(lambda x: _fmt_ptbr_num(x, 2))
            df_bu_view["Giro atual"] = df_bu_view["giro_atual"].round(2)
            df_bu_view["Status giro"] = df_bu_view["status_giro"]
            df_bu_view["Eficiência"] = df_bu_view["eficiencia_pct"].map(lambda x: _fmt_pct(x, 1))
            df_bu_view["% part. consumo"] = df_bu_view["participacao_saida_pct"].map(lambda x: _fmt_pct(x, 1))
            df_bu_view["% part. baseline"] = df_bu_view["participacao_baseline_pct"].map(lambda x: _fmt_pct(x, 1))

            df_bu_view = df_bu_view.rename(columns={
                "area_negocio": "BU"
            })

            df_bu_exibicao = df_bu_view[
            [
                "BU",
                "Baseline inicial (R$)",
                "Entradas SAP (R$)",
                "Base disponível (R$)",
                "Consumo SAP (R$)",
                "Saldo atual (SAP) (R$)",
                "Giro atual",
                "Status giro",
                "Eficiência",
                "% part. consumo",
                "% part. baseline",
            ]
            ]

            st.dataframe(
                estilizar_indicador_giro(
                    df_bu_exibicao,
                    meta_giro=float(meta_giro),
                ),
                column_config={
                    "Giro atual": st.column_config.NumberColumn(
                        "Giro atual",
                        format="%.2f",
                        help=(
                            "Entradas SAP do mês divididas pelo saldo atual "
                            "SAP. Meta definida na barra lateral."
                        ),
                    ),
                    "Status giro": st.column_config.TextColumn(
                        "Status giro",
                        help=(
                            "Verde: meta atingida. Vermelho: abaixo da meta. "
                            "Cinza: giro não calculado por saldo não positivo."
                        ),
                    ),
                },
                width="stretch",
                hide_index=True,
            )

            st.caption(
                f"Giro atual = Entradas SAP do mês ÷ Saldo atual SAP. "
                f"Meta vigente: {float(meta_giro):.2f}."
            )


            st.markdown("### Detalhamento por Diretoria e Segmento")

            somente_saldo_acima_baseline = st.checkbox(
                "Mostrar somente saldos acima do baseline",
                value=False,
                key=f"filtro_saldo_acima_baseline_{mes_ref}",
                help=(
                    "Exibe somente segmentos cujo Saldo atual SAP (R$) "
                    "é maior que o Baseline inicial (R$) do mês."
                ),
            )

            df_segmento = load_eficiencia_segmento_mast(
                db_path,
                mes_ref,
                desconsiderar_mov_343_344,
            )

            if df_segmento.empty:
                st.info(
                    "Sem dados suficientes para detalhar a eficiência "
                    "por Diretoria e Segmento."
                )
            else:
                df_segmento_filtrado = df_segmento.copy()

                # ---------------------------------------------------------
                # Filtro de BU
                # ---------------------------------------------------------
                lista_bu = sorted(
                    df_segmento_filtrado["bu"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

                opcoes_bu = ["Todas"] + lista_bu

                filtro_bu = st.selectbox(
                    "BU",
                    options=opcoes_bu,
                    index=0,
                    key=f"filtro_eficiencia_bu_segmento_{mes_ref}",
                )

                if filtro_bu != "Todas":
                    df_segmento_filtrado = df_segmento_filtrado[
                        df_segmento_filtrado["bu"] == filtro_bu
                    ].copy()

                # ---------------------------------------------------------
                # Filtro de Diretoria
                # As opções dependem da BU selecionada.
                # ---------------------------------------------------------
                lista_diretoria = sorted(
                    df_segmento_filtrado["diretoria"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

                opcoes_diretoria = ["Todas"] + lista_diretoria

                filtro_diretoria = st.selectbox(
                    "Diretoria",
                    options=opcoes_diretoria,
                    index=0,
                    key=f"filtro_eficiencia_diretoria_segmento_{mes_ref}",
                )

                if filtro_diretoria != "Todas":
                    df_segmento_filtrado = df_segmento_filtrado[
                        df_segmento_filtrado["diretoria"]
                        == filtro_diretoria
                    ].copy()

                # ---------------------------------------------------------
                # Filtro operacional do PCP
                #
                # Um saldo atual acima do baseline indica que o estoque
                # terminou o período analisado acima do nível existente na
                # virada do mês. Esses segmentos merecem atenção do PCP
                # porque o estoque não está sendo reduzido abaixo do ponto
                # inicial, apesar do processamento/consumo realizado.
                #
                # A comparação usa os valores numéricos originais. A
                # formatação em R$ acontece somente na camada visual.
                # ---------------------------------------------------------
                if somente_saldo_acima_baseline:
                    df_segmento_filtrado = df_segmento_filtrado[
                        df_segmento_filtrado["saldo_atual_sap_val"]
                        > df_segmento_filtrado["baseline_val"]
                    ].copy()

                if df_segmento_filtrado.empty:
                    st.info(
                        "Nenhum segmento encontrado para os filtros selecionados."
                    )
                else:
                    # -----------------------------------------------------
                    # Recalcula as participações dentro do recorte filtrado.
                    # Isso evita mostrar percentuais referentes ao total geral
                    # quando o usuário seleciona uma BU ou Diretoria.
                    # -----------------------------------------------------
                    total_consumo_filtrado = float(
                        df_segmento_filtrado[
                            "consumo_real_sap_val"
                        ].sum()
                    )

                    df_segmento_filtrado[
                        "participacao_consumo_filtrado_pct"
                    ] = np.where(
                        total_consumo_filtrado > 0,
                        (
                            df_segmento_filtrado[
                                "consumo_real_sap_val"
                            ]
                            / total_consumo_filtrado
                        ),
                        0,
                    )

                    total_baseline_filtrado = float(
                        df_segmento_filtrado["baseline_val"].sum()
                    )

                    df_segmento_filtrado[
                        "participacao_baseline_filtrado_pct"
                    ] = np.where(
                        total_baseline_filtrado > 0,
                        (
                            df_segmento_filtrado["baseline_val"]
                            / total_baseline_filtrado
                        ),
                        0,
                    )

                    # -----------------------------------------------------
                    # Montagem da tabela visual
                    #
                    # Os valores quantitativos permanecem numéricos até a
                    # camada de apresentação. Isso permite ao Streamlit:
                    #
                    # - reconhecer corretamente números e percentuais;
                    # - alinhá-los naturalmente à direita;
                    # - aplicar a formatação localizada do navegador;
                    # - preservar os dados originais para ordenação e filtros.
                    #
                    # Evitamos formatar previamente com _fmt_ptbr_num() e
                    # _fmt_pct(), pois essas funções transformariam os valores
                    # em texto e fariam o dataframe tratá-los como strings.
                    # -----------------------------------------------------
                    df_segmento_view = adicionar_indicador_giro(
                        df_segmento_filtrado,
                        meta_giro=float(meta_giro),
                    )

                    # As colunas monetárias são arredondadas somente na
                    # camada visual. Os valores originais permanecem intactos
                    # em df_segmento_filtrado para cálculos, filtros e indicadores.
                    #
                    # O tipo numérico é preservado para que o Streamlit possa
                    # aplicar format="localized" e manter o alinhamento à direita.
                    df_segmento_view["Baseline inicial (R$)"] = (
                        df_segmento_view["baseline_val"].round(2)
                    )

                    df_segmento_view["Entradas SAP (R$)"] = (
                        df_segmento_view["entradas_val"].round(2)
                    )

                    df_segmento_view["Base disponível (R$)"] = (
                        df_segmento_view["base_disponivel_val"].round(2)
                    )

                    df_segmento_view["Consumo SAP (R$)"] = (
                        df_segmento_view["consumo_real_sap_val"].round(2)
                    )

                    df_segmento_view["Saldo atual SAP (R$)"] = (
                        df_segmento_view["saldo_atual_sap_val"].round(2)
                    )

                    df_segmento_view["Giro atual"] = (
                        df_segmento_view["giro_atual"].round(2)
                    )

                    df_segmento_view["Status giro"] = (
                        df_segmento_view["status_giro"]
                    )

                    df_segmento_view["Eficiência"] = (
                        df_segmento_view["eficiencia_pct"]
                    )

                    df_segmento_view["% part. consumo"] = (
                        df_segmento_view[
                            "participacao_consumo_filtrado_pct"
                        ]
                    )

                    df_segmento_view["% part. baseline"] = (
                        df_segmento_view[
                            "participacao_baseline_filtrado_pct"
                        ]
                    )

                    df_segmento_view = df_segmento_view.rename(
                        columns={
                            "bu": "BU",
                            "diretoria": "Diretoria",
                            "segmento": "Segmento",
                        }
                    )

                    df_segmento_view = df_segmento_view.sort_values(
                        [
                            "BU",
                            "Diretoria",
                            "consumo_real_sap_val",
                        ],
                        ascending=[
                            True,
                            True,
                            False,
                        ],
                    )

                    df_segmento_exibicao = df_segmento_view[
                            [
                                "BU",
                                "Diretoria",
                                "Segmento",
                                "Baseline inicial (R$)",
                                "Entradas SAP (R$)",
                                "Base disponível (R$)",
                                "Consumo SAP (R$)",
                                "Saldo atual SAP (R$)",
                                "Giro atual",
                                "Status giro",
                                "Eficiência",
                                "% part. consumo",
                                "% part. baseline",
                            ]
                    ]

                    st.dataframe(
                        estilizar_indicador_giro(
                            df_segmento_exibicao,
                            meta_giro=float(meta_giro),
                        ),
                        column_config={
                            "Baseline inicial (R$)": st.column_config.NumberColumn(
                                "Baseline inicial (R$)",
                                format="localized",
                            ),
                            "Entradas SAP (R$)": st.column_config.NumberColumn(
                                "Entradas SAP (R$)",
                                format="localized",
                            ),
                            "Base disponível (R$)": st.column_config.NumberColumn(
                                "Base disponível (R$)",
                                format="localized",
                            ),
                            "Consumo SAP (R$)": st.column_config.NumberColumn(
                                "Consumo SAP (R$)",
                                format="localized",
                            ),
                            "Saldo atual SAP (R$)": st.column_config.NumberColumn(
                                "Saldo atual SAP (R$)",
                                format="localized",
                            ),
                            "Giro atual": st.column_config.NumberColumn(
                                "Giro atual",
                                format="%.2f",
                                help=(
                                    "Entradas SAP do mês divididas pelo saldo "
                                    "atual SAP. Meta definida na barra lateral."
                                ),
                            ),
                            "Status giro": st.column_config.TextColumn(
                                "Status giro",
                                help=(
                                    "Verde: meta atingida. Vermelho: abaixo da "
                                    "meta. Cinza: giro não calculado por saldo "
                                    "não positivo."
                                ),
                            ),
                            "Eficiência": st.column_config.NumberColumn(
                                "Eficiência",
                                format="percent",
                            ),
                            "% part. consumo": st.column_config.NumberColumn(
                                "% part. consumo",
                                format="percent",
                            ),
                            "% part. baseline": st.column_config.NumberColumn(
                                "% part. baseline",
                                format="percent",
                            ),
                        },
                        width="stretch",
                        hide_index=True,
                    )

                    st.caption(
                        f"Giro atual = Entradas SAP do mês ÷ Saldo atual "
                        f"SAP. Meta vigente: {float(meta_giro):.2f}."
                    )

            st.markdown("### Participação das BUs nas consumos do mês")

            df_plot_saida = df_bu.copy()

            df_plot_saida = df_plot_saida.sort_values(
                "saidas_val",
                ascending=True
            )

            fig_saida = px.bar(
                df_plot_saida,
                x="participacao_saida_pct",
                y="area_negocio",
                orientation="h",
                text="participacao_saida_pct",
                color="classe_relevancia",
                custom_data=["saidas_val", "baseline_val", "participacao_baseline_pct"],
                labels={
                    "participacao_saida_pct": "% do consumo",
                    "area_negocio": "BU"
                },
                color_discrete_map={
                    "Relevante": "#2F6BBA",
                    "Baixo impacto": "#B0B0B0",
                },
                title=None
            )

            fig_saida.update_traces(
                texttemplate="%{text:.1%}",
                textposition="outside",
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Participação no consumo: %{x:.1%}<br>"
                    "Consumo SAP: R$ %{customdata[0]:,.2f}<br>"
                    "Baseline: R$ %{customdata[1]:,.2f}<br>"
                    "% do baseline: %{customdata[2]:.1%}"
                    "<extra></extra>"
                )
            )

            fig_saida.update_layout(
                xaxis_tickformat=".0%",
                yaxis_title=None,
                xaxis_title=None,
                height=max(350, len(df_plot_saida) * 55),
            )

            st.plotly_chart(
                fig_saida,
                width="stretch",
                key=f"grafico_bu_saida_{mes_ref}"
            )

            st.markdown("### Eficiência proporcional por BU")

            df_plot_eff = df_bu.copy()

            # Ordena pelo peso financeiro do baseline
            df_plot_eff = df_plot_eff.sort_values(
                "baseline_val",
                ascending=True
            )

            fig_eff = px.bar(
                df_plot_eff,
                x="eficiencia_pct",
                y="area_negocio",
                orientation="h",
                text="eficiencia_pct",
                color="classe_relevancia",
                custom_data=[
                    "baseline_val",
                    "saidas_val",
                    "baseline_restante",
                    "participacao_baseline_pct"
                ],
                color_discrete_map={
                    "Relevante": "#2F6BBA",
                    "Baixo impacto": "#B0B0B0",
                },
                labels={
                    "eficiencia_pct": "Eficiência",
                    "area_negocio": "BU",
                    "classe_relevancia": "Impacto financeiro",
                },
            )

            fig_eff.update_traces(
                texttemplate="%{text:.1%}",
                textposition="outside",
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Eficiência: %{x:.1%}<br>"
                    "Baseline: R$ %{customdata[0]:,.2f}<br>"
                    "Consumo SAP: R$ %{customdata[1]:,.2f}<br>"
                     "Saldo atual SAP: R$ %{customdata[2]:,.2f}<br>"
                    "% do baseline: %{customdata[3]:.1%}"
                    "<extra></extra>"
                )
            )

            fig_eff.update_layout(
                xaxis_tickformat=".0%",
                yaxis_title=None,
                xaxis_title=None,
                height=max(350, len(df_plot_eff) * 55),
            )

            st.plotly_chart(
                fig_eff,
                width="stretch",
                key=f"grafico_bu_eficiencia_{mes_ref}"
            )

        # KPI — Ritmo necessário
        try:
            ano, mes = map(int, mes_ref.split("-"))
            hoje = pd.Timestamp.today().normalize()
            fim_mes = pd.Timestamp(ano, mes, 1) + pd.offsets.MonthEnd(0)

            dias_uteis_restantes = np.busday_count(
                hoje.date(),
                (fim_mes + pd.Timedelta(days=1)).date()
            )
        except Exception:
            dias_uteis_restantes = None

        if baseline_restante not in (None, 0) and dias_uteis_restantes not in (None, 0):
            ritmo_necessario = baseline_restante / dias_uteis_restantes
        else:
            ritmo_necessario = None

        st.divider()

        # Ritmo do mês (projeção)
        try:
            inicio_mes = pd.Timestamp(ano, mes, 1)
            dias_uteis_decorridos = np.busday_count(
                inicio_mes.date(),
                (hoje + pd.Timedelta(days=1)).date()
            )
        except Exception:
            dias_uteis_decorridos = None

        if saidas_val_mes not in (None, 0) and dias_uteis_decorridos not in (None, 0):
            ritmo_atual = float(saidas_val_mes) / float(dias_uteis_decorridos)
        else:
            ritmo_atual = None

        if baseline_restante not in (None, 0) and ritmo_atual not in (None, 0) and dias_uteis_restantes not in (None, 0):
            baseline_restante_proj_fechamento = max(
                0.0,
                float(baseline_restante) - float(ritmo_atual) * float(dias_uteis_restantes)
            )
        else:
            baseline_restante_proj_fechamento = None

        with st.expander("Ritmo do mês (projeção)", expanded=False):
            p1, p2, p3, p4, p5 = st.columns(5)

            p1.metric(
                "Dias úteis decorridos",
                f"{dias_uteis_decorridos}"
                if dias_uteis_decorridos is not None else "NA"
            )

            p2.metric(
                "Dias úteis restantes",
                f"{dias_uteis_restantes}"
                if dias_uteis_restantes is not None else "NA"
            )

            p3.metric(
                "Ritmo atual (R$/dia útil)",
                f"{ritmo_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if ritmo_atual is not None else "NA"
            )

            p4.metric(
                "Ritmo necessário p/ zerar baseline (R$/dia)",
                f"{ritmo_necessario:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if ritmo_necessario is not None else "NA"
            )

            p5.metric(
                "Baseline restante proj. no fechamento (R$)",
                f"{baseline_restante_proj_fechamento:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if baseline_restante_proj_fechamento is not None else "NA"
            )

            df_mb_d = load_mb51_diario_real_mes(
                db_path,
                mes_ref,
                desconsiderar_mov_343_344,
            )

            if df_mb_d is not None and not df_mb_d.empty and "dia" in df_mb_d.columns and "saidas_val" in df_mb_d.columns:
                df_plot = df_mb_d[["dia", "saidas_val"]].copy()
                df_plot["dia"] = pd.to_datetime(df_plot["dia"], errors="coerce")
                df_plot["saidas_val"] = pd.to_numeric(df_plot["saidas_val"], errors="coerce").fillna(0.0)

                fig = px.bar(
                    df_plot,
                    x="dia",
                    y="saidas_val",
                    labels={"dia": "Dia", "saidas_val": "Saídas (R$)"},
                    title="Consumo diário (Saídas) — comparação com ritmo",
                )

                fig.update_traces(
                    text=df_plot["saidas_val"],
                    texttemplate="R$ %{text:,.0f}",
                    textposition="inside",
                    textangle=-90,
                    insidetextanchor="middle",
                )

                fig.update_layout(
                    uniformtext_minsize=9,
                    uniformtext_mode="hide",
                    yaxis_title=None,
                    xaxis_title=None,
                )

                if ritmo_necessario is not None:
                    fig.add_hline(
                        y=float(ritmo_necessario),
                        line_width=2,
                        line_color="red",
                        annotation_font_color="red",
                        annotation_text="Ritmo necessário",
                        annotation_position="top left",
                    )

                if ritmo_atual is not None:
                    fig.add_hline(
                        y=float(ritmo_atual),
                        line_width=2,
                        line_dash="dot",
                        line_color="orange",
                        annotation_font_color="orange",
                        annotation_text="Ritmo atual (média)",
                        annotation_position="top left",
                    )

                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Sem série diária disponível para plotar o consumo (Saídas) no mês.")

        # Auditoria MB51
        st.markdown("### Auditoria MB51 (mês)")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Entradas reais (R$)", f"{row['entradas_reais_val_mes']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        a2.metric("Saídas reais (R$)", f"{row['saidas_reais_val_mes']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        a3.metric("Eficiência (%)", f"{row['eficiencia_val_ratio']:.2%}".replace(".", ",") if row.get("eficiencia_val_ratio") is not None else "NA")
        a4.metric("Consumo líquido (R$)", f"{row['consumo_liq_val_mes']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.markdown("### 📸 Foto do baseline e do saldo")
        df_foto = pd.DataFrame([{
            "Mês ref": row.get("mes_ref", ""),
            "Data baseline (foto inicial)": row.get("baseline_date", ""),
            "Baseline (R$)": float(row.get("val_base_total", 0.0) or 0.0),
            "Data saldo atual (snapshot)": row.get("last_snapshot_date", ""),
            "Saldo atual (R$)": float(row.get("val_atual_total", 0.0) or 0.0),
        }])

        df_foto["Baseline (R$)"] = df_foto["Baseline (R$)"].map(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        df_foto["Saldo atual (R$)"] = df_foto["Saldo atual (R$)"].map(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.dataframe(df_foto, width="stretch")

        st.markdown("### 📊 Entradas x Saídas (mês)")
        entradas_val = float(row.get("entradas_reais_val_mes", 0.0) or 0.0)
        saidas_val   = float(row.get("saidas_reais_val_mes", 0.0) or 0.0)

        falta_consumir_entradas = max(0.0, entradas_val - saidas_val)
        excedente_vs_entradas   = max(0.0, saidas_val - entradas_val)

        df_barras = pd.DataFrame({
            "Item": ["Entradas (R$)", "Saídas (R$)", "Falta p/ consumir entradas (R$)"],
            "Valor": [entradas_val, saidas_val, falta_consumir_entradas],
        })

        fig = px.bar(df_barras, x="Item", y="Valor", text="Valor", title=None)
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
        fig.update_layout(yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig, width="stretch")

        if excedente_vs_entradas > 0:
            st.success(
                f"Saídas já superaram as entradas do mês em "
                f"{excedente_vs_entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
        else:
            st.warning(
                f"Ainda faltam "
                f"{falta_consumir_entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                + " em saídas para consumir tudo que entrou no mês."
            )

        st.divider()

        df_snap = load_snapshot_saldo_mes(db_path, mes_ref)
        if not df_snap.empty:
            fig_line = px.line(df_snap, x="dia", y="saldo_val", title=f"Saldo diário (snapshot) — {mes_ref}")

            meta_saldo = row.get("meta_saldo_bi_val", None)
            if meta_saldo not in (None, 0):
                fig_line.add_hline(
                    y=float(meta_saldo),
                    line_dash="dash",
                    annotation_text="Meta de saldo (BI)",
                    annotation_position="top left",
                )

            st.plotly_chart(fig_line, width="stretch", key=f"line_saldo_{mes_ref}")
            st.divider()

    with tab2:
        st.subheader(f"Séries diárias — {mes_ref}")

        df_mb_d = load_mb51_diario_real_mes(
            db_path,
            mes_ref,
            desconsiderar_mov_343_344,
)
        df_snap = load_snapshot_saldo_mes(db_path, mes_ref)

        st.markdown("**MB51 REAL por dia**")

        if df_mb_d is not None and not df_mb_d.empty:
            for col in [
                "entradas_val",
                "saidas_val",
                "consumo_liq_val",
                "entradas_qtd",
                "saidas_qtd",
                "consumo_liq_qtd",
            ]:
                if col in df_mb_d.columns:
                    df_mb_d[col] = pd.to_numeric(
                        df_mb_d[col],
                        errors="coerce",
                    ).fillna(0)

            entradas_val_mes = float(df_mb_d["entradas_val"].sum())
            saidas_val_mes = float(df_mb_d["saidas_val"].sum())
            consumo_val_mes = float(df_mb_d["consumo_liq_val"].sum())

            entradas_qtd_mes = float(df_mb_d["entradas_qtd"].sum())
            saidas_qtd_mes = float(df_mb_d["saidas_qtd"].sum())
            consumo_qtd_mes = float(df_mb_d["consumo_liq_qtd"].sum())
        else:
            entradas_val_mes = 0.0
            saidas_val_mes = 0.0
            consumo_val_mes = 0.0

            entradas_qtd_mes = 0.0
            saidas_qtd_mes = 0.0
            consumo_qtd_mes = 0.0

        a, b, c = st.columns(3)

        a.metric(
            "Entradas mês (valor)",
            f"{entradas_val_mes:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        b.metric(
            "Saídas mês (valor)",
            f"{saidas_val_mes:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        c.metric(
            "Consumo líquido mês (valor)",
            f"{consumo_val_mes:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        d, e, f = st.columns(3)

        d.metric(
            "Entradas mês (qtd)",
            f"{entradas_qtd_mes:,.3f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        e.metric(
            "Saídas mês (qtd)",
            f"{saidas_qtd_mes:,.3f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        f.metric(
            "Consumo líquido mês (qtd)",
            f"{consumo_qtd_mes:,.3f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", "."),
        )

        st.markdown("### KPI Diário REAL (MB51) — tabela")

        if df_mb_d is None or df_mb_d.empty:
            st.dataframe(df_mb_d, width="stretch")
        else:
            df_mb_view = df_mb_d.copy()

            for col in ["entradas_qtd", "saidas_qtd", "consumo_liq_qtd",
                        "entradas_val", "saidas_val", "consumo_liq_val"]:
                if col in df_mb_view.columns:
                    df_mb_view[col] = pd.to_numeric(df_mb_view[col], errors="coerce")

            fmt = {}
            for col in ["entradas_qtd", "saidas_qtd", "consumo_liq_qtd"]:
                if col in df_mb_view.columns:
                    fmt[col] = lambda x: _fmt_ptbr_num(x, 0)

            for col in ["entradas_val", "saidas_val", "consumo_liq_val"]:
                if col in df_mb_view.columns:
                    fmt[col] = lambda x: _fmt_ptbr_num(x, 2)

            styled = df_mb_view.style.format(fmt, na_rep="")
            st.dataframe(styled, width="stretch")

        with st.expander("Ver tabela de saldo (snapshot) por dia (auditoria)", expanded=False):
            if df_snap is None or df_snap.empty:
                st.dataframe(df_snap, width="stretch")
            else:
                df_snap_view = df_snap.copy()
                for col in ["saldo_val", "saldo_qtd"]:
                    if col in df_snap_view.columns:
                        df_snap_view[col] = pd.to_numeric(df_snap_view[col], errors="coerce")

                fmt2 = {}
                if "saldo_val" in df_snap_view.columns:
                    fmt2["saldo_val"] = lambda x: _fmt_ptbr_num(x, 2)
                if "saldo_qtd" in df_snap_view.columns:
                    fmt2["saldo_qtd"] = lambda x: _fmt_ptbr_num(x, 0)

                styled2 = df_snap_view.style.format(fmt2, na_rep="")
                st.dataframe(styled2, width="stretch")

        if df_mb_d is not None and not df_mb_d.empty:
            df_val = df_mb_d[["dia", "consumo_liq_val"]].copy()
            fig_d1 = px.line(df_val, x="dia", y="consumo_liq_val",
                             title=f"MB51 REAL — consumo líquido (valor) por dia ({mes_ref})")
            st.plotly_chart(fig_d1, width="stretch", key=f"d1_mb51_cons_val_{mes_ref}")

            df_qtd = df_mb_d[["dia", "consumo_liq_qtd"]].copy()
            fig_d2 = px.line(df_qtd, x="dia", y="consumo_liq_qtd",
                             title=f"MB51 REAL — consumo líquido (qtd) por dia ({mes_ref})")
            st.plotly_chart(fig_d2, width="stretch", key=f"d2_mb51_cons_qtd_{mes_ref}")

        if df_snap is not None and not df_snap.empty:
            fig_d3 = px.line(df_snap, x="dia", y="saldo_val", title=f"Saldo diário (snapshot) — {mes_ref}")
            st.plotly_chart(fig_d3, width="stretch", key=f"d3_saldo_val_{mes_ref}")

    with tab3:
        st.subheader("Ataque por Quadrantes — MAST (valor e quantidade)")

        cA, cB, cC = st.columns([1, 1, 1])
        with cA:
            p = st.slider("Percentil de corte (P)", min_value=0.50, max_value=0.95, value=0.70, step=0.05)
        with cB:
            top_n = st.number_input("Top N (detalhe)", min_value=10, max_value=2000, value=200, step=10)
        with cC:
            somente_delta_positivo = st.checkbox("Somente materiais com delta positivo", value=True)

        df_res, df_det, cut_val, cut_qtd = load_ataque_quadrantes_mes(db_path, mes_ref, p=float(p))

        if df_res.empty or df_det.empty:
            st.warning("Sem dados suficientes para montar quadrantes (baseline/último snapshot/dimensões).")
            st.stop()

        st.caption(
            f"Cortes (P{int(p*100)}): "
            f"cut_val={cut_val:,.2f} | cut_qtd={cut_qtd:,.3f}"
            .replace(",", "X").replace(".", ",").replace("X", ".")
        )

        st.markdown("**Resumo por quadrante**")
        df_res_view = df_res.copy()

        for col in ["qt_materiais", "soma_delta_val", "soma_delta_qtd"]:
            if col in df_res_view.columns:
                df_res_view[col] = pd.to_numeric(df_res_view[col], errors="coerce")

        fmt = {}
        if "qt_materiais" in df_res_view.columns:
            fmt["qt_materiais"] = lambda x: _fmt_ptbr_num(x, 0)
        if "soma_delta_val" in df_res_view.columns:
            fmt["soma_delta_val"] = lambda x: _fmt_ptbr_num(x, 2)
        if "soma_delta_qtd" in df_res_view.columns:
            fmt["soma_delta_qtd"] = lambda x: _fmt_ptbr_num(x, 0)

        styled_res = df_res_view.style.format(fmt, na_rep="")
        st.dataframe(styled_res, width="stretch")

        quad_sel = st.selectbox("Escolha o quadrante para detalhar", options=df_res["quadrante"].tolist())
        st.markdown(f"**Detalhe — {quad_sel}**")

        df_f = df_det[df_det["quadrante"] == quad_sel].copy()

        if somente_delta_positivo:
            df_f = df_f[(df_f["delta_val"] > 0) | (df_f["delta_qtd"] > 0)].copy()

        filtros = st.expander("Filtros (dimensões)", expanded=True)

        with filtros:
            f1, f2, f3, f4 = st.columns(4)

            # ---------------------------------------------------------
            # BU
            # ---------------------------------------------------------
            if "bu" in df_f.columns:
                bu_norm = (
                    df_f["bu"]
                    .fillna("SEM_BU")
                    .astype(str)
                    .str.strip()
                )

                opts_bu = sorted([
                    x for x in bu_norm.unique().tolist()
                    if x != ""
                ])

                bu_sel = f1.multiselect(
                    "BU",
                    options=opts_bu,
                    default=[],
                    key="f_bu",
                )
            else:
                bu_sel = []

            # ---------------------------------------------------------
            # Diretoria
            # ---------------------------------------------------------
            if "diretoria" in df_f.columns:
                dir_norm = (
                    df_f["diretoria"]
                    .fillna("SEM_DIRETORIA")
                    .astype(str)
                    .str.strip()
                )

                opts_dir = sorted([
                    x for x in dir_norm.unique().tolist()
                    if x != ""
                ])

                diretoria_sel = f2.multiselect(
                    "Diretoria",
                    options=opts_dir,
                    default=[],
                    key="f_diretoria",
                )
            else:
                diretoria_sel = []

            # ---------------------------------------------------------
            # Segmento
            # ---------------------------------------------------------
            if "segmento" in df_f.columns:
                seg_norm = (
                    df_f["segmento"]
                    .fillna("SEM_SEGMENTO")
                    .astype(str)
                    .str.strip()
                )

                opts_seg = sorted([
                    x for x in seg_norm.unique().tolist()
                    if x != ""
                ])

                segmento_sel = f3.multiselect(
                    "Segmento",
                    options=opts_seg,
                    default=[],
                    key="f_segmento",
                )
            else:
                segmento_sel = []

            # ---------------------------------------------------------
            # Processamento
            # ---------------------------------------------------------
            if "processamento" in df_f.columns:
                proc_norm = (
                    df_f["processamento"]
                    .fillna("SEM_PROCESSAMENTO")
                    .astype(str)
                    .str.strip()
                )

                opts_proc = sorted([
                    x for x in proc_norm.unique().tolist()
                    if x != ""
                ])

                proc_sel = f4.multiselect(
                    "Processamento",
                    options=opts_proc,
                    default=[],
                    key="f_proc",
                )
            else:
                proc_sel = []

        # -------------------------------------------------------------
        # Aplica os filtros selecionados.
        # -------------------------------------------------------------
        if bu_sel and "bu" in df_f.columns:
            bu_norm = (
                df_f["bu"]
                .fillna("SEM_BU")
                .astype(str)
                .str.strip()
            )
            df_f = df_f[bu_norm.isin(bu_sel)].copy()

        if diretoria_sel and "diretoria" in df_f.columns:
            dir_norm = (
                df_f["diretoria"]
                .fillna("SEM_DIRETORIA")
                .astype(str)
                .str.strip()
            )
            df_f = df_f[dir_norm.isin(diretoria_sel)].copy()

        if segmento_sel and "segmento" in df_f.columns:
            seg_norm = (
                df_f["segmento"]
                .fillna("SEM_SEGMENTO")
                .astype(str)
                .str.strip()
            )
            df_f = df_f[seg_norm.isin(segmento_sel)].copy()

        if proc_sel and "processamento" in df_f.columns:
            proc_norm = (
                df_f["processamento"]
                .fillna("SEM_PROCESSAMENTO")
                .astype(str)
                .str.strip()
            )
            df_f = df_f[proc_norm.isin(proc_sel)].copy()

        if df_f.empty:
            st.warning("Sem dados para os filtros selecionados.")
            st.stop()

        df_f = (
            df_f.sort_values(["delta_val", "delta_qtd"], ascending=[False, False])
                .head(int(top_n))
                .copy()
        )

        df_p = df_f.copy()
        df_p["delta_val_pos"] = pd.to_numeric(df_p.get("delta_val", 0), errors="coerce").fillna(0).clip(lower=0)
        df_p["delta_qtd_pos"] = pd.to_numeric(df_p.get("delta_qtd", 0), errors="coerce").fillna(0).clip(lower=0)

        df_p = (
            df_p.sort_values(["delta_val_pos", "delta_qtd_pos"], ascending=[False, False])
                .reset_index(drop=True)
        )

        total_val = float(df_p["delta_val_pos"].sum())
        total_qtd = float(df_p["delta_qtd_pos"].sum())

        if total_val > 0:
            df_p["share_delta_val"] = df_p["delta_val_pos"] / total_val
            df_p["cum_share_val"] = df_p["share_delta_val"].cumsum()
        else:
            df_p["share_delta_val"] = 0.0
            df_p["cum_share_val"] = 0.0

        if total_qtd > 0:
            df_p["share_delta_qtd"] = df_p["delta_qtd_pos"] / total_qtd
            df_p["cum_share_qtd"] = df_p["share_delta_qtd"].cumsum()
        else:
            df_p["share_delta_qtd"] = 0.0
            df_p["cum_share_qtd"] = 0.0

        pareto_cut = st.slider("Pareto (acumulado alvo)", min_value=0.50, max_value=0.95, value=0.80, step=0.05)

        if total_val > 0:
            n_pareto_val = int((df_p["cum_share_val"] <= pareto_cut).sum())
            n_pareto_val = max(n_pareto_val, 1)
        else:
            n_pareto_val = 0

        if total_qtd > 0:
            n_pareto_qtd = int((df_p["cum_share_qtd"] <= pareto_cut).sum())
            n_pareto_qtd = max(n_pareto_qtd, 1)
        else:
            n_pareto_qtd = 0

        st.caption(
            f"Pareto (delta_val): {n_pareto_val} materiais explicam ~{int(pareto_cut*100)}% do aumento de valor | "
            f"Pareto (delta_qtd): {n_pareto_qtd} materiais explicam ~{int(pareto_cut*100)}% do aumento de quantidade"
        )

        cols_show = [
            "material", "descricao", "quadrante",
            "delta_val", "delta_qtd",

            # Saldo atual SAP — ajuda o responsável pelo estoque
            # a entender quanto existe agora para atacar.
            "qtd_atual", "val_atual",

            "share_delta_val", "cum_share_val",
            "share_delta_qtd", "cum_share_qtd",
            "bu", "diretoria", "segmento", "processamento"
        ]
        cols_show = [c for c in cols_show if c in df_p.columns]

        df_view = df_p[cols_show].head(int(top_n)).copy()
        df_view_pt = df_pt(df_view)

        fmtv = {}
        if "Variação de Valor (R$)" in df_view_pt.columns:
            fmtv["Variação de Valor (R$)"] = lambda x: _fmt_ptbr_num(x, 2)
        if "Variação de Quantidade" in df_view_pt.columns:
            fmtv["Variação de Quantidade"] = lambda x: _fmt_ptbr_num(x, 0)

        if "Saldo atual (R$)" in df_view_pt.columns:
            fmtv["Saldo atual (R$)"] = lambda x: _fmt_ptbr_num(x, 2)

        if "Saldo atual (qtd)" in df_view_pt.columns:
            fmtv["Saldo atual (qtd)"] = lambda x: _fmt_ptbr_num(x, 0)

        for col in ["% do Impacto em Valor", "% Acumulado do Impacto em Valor",
                    "% do Impacto em Quantidade", "% Acumulado do Impacto em Quantidade"]:
            if col in df_view_pt.columns:
                fmtv[col] = lambda x: _fmt_pct(x, 2)

        styled = df_view_pt.style.format(fmtv, na_rep="")
        st.dataframe(styled, width="stretch")
        st.divider()

        # --- EXPORTAÇÃO ---
        params_export = {
            "mes_ref": mes_ref,
            "quadrante": quad_sel,
            "percentil_P": float(p),
            "cut_val": float(cut_val),
            "cut_qtd": float(cut_qtd),
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        xlsx_bytes = build_excel_export(
            df_pareto_det=df_f,
            df_resumo=df_res,
            params=params_export,
        )

        nome_arquivo = f"MAST_PARETO_{mes_ref}_{quad_sel}_P{int(p*100)}.xlsx"

        st.download_button(
            label="Baixar Excel (Pareto + Resumo + Parâmetros)",
            data=xlsx_bytes,
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_pareto_{mes_ref}_{quad_sel}_{int(p*100)}",
            # O download não precisa reexecutar a página. Evitar esse rerun
            # também previne referências obsoletas ao XLSX mantido em memória.
            on_click="ignore",
        )

    with tab4:
        st.markdown("### Evolução mensal — Entradas, Saldo e Giro")

        st.caption(
            "Acompanhamento financeiro do MAST com base na mesma regra "
            "homologada do BI mensal."
        )

        # O mês atual é identificado pelo relógio do computador que executa
        # o Streamlit. Ele pode ser mostrado como parcial, mas não participa
        # da tendência enquanto ainda não estiver encerrado.
        mes_atual = datetime.now().strftime("%Y-%m")
        anos_disponiveis = sorted({mes[:4] for mes in meses})

        controle_periodo, controle_ano = st.columns([1, 1])

        with controle_periodo:
            tipo_periodo = st.radio(
                "Período de visualização",
                options=[
                    "Últimos 12 meses",
                    "Ano calendário",
                ],
                horizontal=True,
                key="evolucao_tipo_periodo",
            )

        with controle_ano:
            if tipo_periodo == "Ano calendário":
                # Por padrão, abre o ano correspondente ao mês selecionado
                # na barra lateral, quando ele existir na base.
                ano_padrao = mes_ref[:4]

                indice_ano = (
                    anos_disponiveis.index(ano_padrao)
                    if ano_padrao in anos_disponiveis
                    else len(anos_disponiveis) - 1
                )

                ano_selecionado = st.selectbox(
                    "Ano",
                    options=anos_disponiveis,
                    index=indice_ano,
                    key="evolucao_ano",
                )
            else:
                ano_selecionado = None
                st.caption(
                    "O período deslizante usa os 12 meses mais recentes "
                    "disponíveis no banco."
                )

        # Meses futuros, caso existam por alguma carga antecipada, não entram
        # no acompanhamento realizado.
        meses_ate_atual = [
            mes
            for mes in meses
            if mes <= mes_atual
        ]

        if tipo_periodo == "Últimos 12 meses":
            meses_candidatos = meses_ate_atual
        else:
            meses_candidatos = [
                mes
                for mes in meses_ate_atual
                if mes.startswith(str(ano_selecionado))
            ]

        # A opção só é exibida quando o mês corrente realmente existe na base.
        # O padrão é não incluir o mês parcial, evitando distorção na leitura.
        incluir_mes_atual = False

        if mes_atual in meses_candidatos:
            incluir_mes_atual = st.checkbox(
                "Incluir mês atual (parcial)",
                value=False,
                help=(
                    "Mostra o mês em andamento no gráfico e nos indicadores. "
                    "Mesmo quando exibido, ele não participa da linha de tendência."
                ),
                key="evolucao_incluir_mes_atual",
            )

        meses_periodo = [
            mes
            for mes in meses_candidatos
            if incluir_mes_atual or mes != mes_atual
        ]

        # O corte dos 12 meses acontece depois da eventual exclusão do mês
        # corrente. Assim, o padrão mostra até 12 meses efetivamente fechados.
        if tipo_periodo == "Últimos 12 meses":
            meses_periodo = meses_periodo[-12:]

        df_evolucao = load_evolucao_mensal_mast(
            db_path,
            tuple(meses_periodo),
            desconsiderar_mov_343_344,
        )

        if df_evolucao.empty:
            st.warning(
                "Não há snapshots mensais suficientes para montar "
                "a evolução no período selecionado."
            )
        else:
            # O rótulo MM/AAAA não depende da configuração regional do Windows.
            # Um asterisco identifica visualmente o mês ainda em andamento.
            df_evolucao["parcial"] = (
                df_evolucao["mes_ref"] == mes_atual
            )

            df_evolucao["mes_label"] = (
                df_evolucao["mes_ref"]
                .str.slice(5, 7)
                .str.cat(
                    df_evolucao["mes_ref"].str.slice(0, 4),
                    sep="/",
                )
            )

            df_evolucao.loc[
                df_evolucao["parcial"],
                "mes_label",
            ] += " *"

            # A regressão linear é calculada somente com meses fechados.
            # O coeficiente angular representa quanto o saldo tende a variar,
            # em reais, a cada mês do período analisado.
            df_tendencia = (
                df_evolucao.loc[
                    ~df_evolucao["parcial"],
                    ["mes_label", "saldo_val"],
                ]
                .dropna()
                .reset_index(drop=True)
            )

            inclinacao_tendencia = None

            if len(df_tendencia) >= 2:
                eixo_tempo = np.arange(len(df_tendencia), dtype=float)

                inclinacao_tendencia, intercepto_tendencia = np.polyfit(
                    eixo_tempo,
                    df_tendencia["saldo_val"].to_numpy(dtype=float),
                    1,
                )

                df_tendencia["tendencia_saldo"] = (
                    inclinacao_tendencia * eixo_tempo
                    + intercepto_tendencia
                )

            entrada_media = float(df_evolucao["entradas_val"].mean())
            saldo_inicial = float(df_evolucao.iloc[0]["saldo_val"])
            saldo_final = float(df_evolucao.iloc[-1]["saldo_val"])
            variacao_saldo = saldo_final - saldo_inicial

            # A última linha representa o mês mais recente efetivamente
            # exibido no período, seja ele fechado ou parcial.
            ultimo_registro = df_evolucao.iloc[-1]

            ultimo_mes_ref = str(ultimo_registro["mes_ref"])
            ultimo_mes_label = (
                f"{ultimo_mes_ref[5:7]}/{ultimo_mes_ref[0:4]}"
            )

            ultimo_mes_situacao = (
                "parcial"
                if bool(ultimo_registro["parcial"])
                else "fechado"
            )

            entrada_ultimo_mes = float(
                ultimo_registro["entradas_val"]
            )

            giro_ultimo_mes = ultimo_registro["giro"]

            meses_meta = int(
                (
                    df_evolucao["giro"].notna()
                    & (df_evolucao["giro"] >= float(meta_giro))
                ).sum()
            )

            total_meses_com_giro = int(
                df_evolucao["giro"].notna().sum()
            )

            # A primeira linha responde imediatamente: como terminou o mês
            # mais recente mostrado no painel?
            st.markdown(
                f"#### Último mês do período — "
                f"{ultimo_mes_label} ({ultimo_mes_situacao})"
            )

            atual1, atual2, atual3 = st.columns(3)

            atual1.metric(
                "Entrada do mês",
                f"R$ {_fmt_ptbr_num(entrada_ultimo_mes, 2)}",
            )

            # Como aumento de estoque é desfavorável, delta_color="inverse"
            # mostra redução em verde e aumento em vermelho.
            atual2.metric(
                "Saldo do mês",
                f"R$ {_fmt_ptbr_num(saldo_final, 2)}",
                delta=(
                    "Variação no período: "
                    f"R$ {_fmt_ptbr_num(variacao_saldo, 2)}"
                ),
                delta_color="inverse",
            )

            atual3.metric(
                "Giro do mês",
                (
                    f"{float(giro_ultimo_mes):.2f}".replace(".", ",")
                    if not pd.isna(giro_ultimo_mes)
                    else "Não calculado"
                ),
            )

            # A segunda linha resume o comportamento de todo o intervalo.
            st.markdown("#### Resumo do período")

            resumo1, resumo2, resumo3, resumo4 = st.columns(4)

            resumo1.metric(
                "Entrada média mensal",
                f"R$ {_fmt_ptbr_num(entrada_media, 2)}",
            )

            resumo2.metric(
                "Saldo inicial",
                f"R$ {_fmt_ptbr_num(saldo_inicial, 2)}",
            )

            resumo3.metric(
                "Tendência do saldo",
                (
                    f"R$ {_fmt_ptbr_num(inclinacao_tendencia, 2)}/mês"
                    if inclinacao_tendencia is not None
                    else "Dados insuficientes"
                ),
            )

            resumo4.metric(
                f"Meses com giro ≥ {float(meta_giro):.2f}",
                f"{meses_meta} de {total_meses_com_giro}",
            )

            if inclinacao_tendencia is None:
                st.info(
                    "São necessários pelo menos dois meses fechados "
                    "para calcular a tendência linear do saldo."
                )
            elif inclinacao_tendencia < 0:
                st.success(
                    "A tendência linear indica redução média do saldo "
                    f"de R$ {_fmt_ptbr_num(abs(inclinacao_tendencia), 2)} "
                    "por mês no período."
                )
            elif inclinacao_tendencia > 0:
                st.warning(
                    "A tendência linear indica aumento médio do saldo "
                    f"de R$ {_fmt_ptbr_num(inclinacao_tendencia, 2)} "
                    "por mês no período."
                )
            else:
                st.info(
                    "A tendência linear indica estabilidade do saldo "
                    "no período."
                )

            # make_subplots permite combinar grandezas de escalas diferentes:
            # valores financeiros usam o eixo esquerdo e o giro usa o direito.
            figura = make_subplots(
                specs=[[{"secondary_y": True}]]
            )

            entradas_formatadas = df_evolucao["entradas_val"].map(
                lambda valor: f"R$ {_fmt_ptbr_num(valor, 2)}"
            )

            # Valor arredondado para exibição vertical dentro das barras.
            entradas_rotulos = df_evolucao["entradas_val"].map(
                lambda valor: f"R$ {_fmt_ptbr_num(valor, 0)}"
            )

            saldos_formatados = df_evolucao["saldo_val"].map(
                lambda valor: f"R$ {_fmt_ptbr_num(valor, 2)}"
            )

            giros_formatados = df_evolucao["giro"].map(
                lambda valor: (
                    ""
                    if pd.isna(valor)
                    else f"{float(valor):.2f}".replace(".", ",")
                )
            )

            # Barras: total de entradas financeiras de cada mês.
            figura.add_trace(
                go.Bar(
                    x=df_evolucao["mes_label"],
                    y=df_evolucao["entradas_val"],
                    name="Entradas",
                                        marker_color="#4C78A8",
                    opacity=0.85,
                    text=entradas_rotulos,
                    texttemplate="%{text}",
                    textposition="inside",
                    textangle=-90,
                    # Mantém todos os valores próximos à base das barras,
                    # evitando que cada altura produza uma posição diferente.
                    insidetextanchor="start",
                    constraintext="none",
                    textfont={
                        "color": "yellow",
                        "size": 14,
                    },
                    customdata=entradas_formatadas,
                    hovertemplate=(
                        "%{x}<br>"
                        "Entradas: %{customdata}"
                        "<extra></extra>"
                    ),
                ),
                secondary_y=False,
            )

            # Linha principal: saldo do último snapshot existente em cada mês.
            figura.add_trace(
                go.Scatter(
                    x=df_evolucao["mes_label"],
                    y=df_evolucao["saldo_val"],
                    name="Saldo",
                    mode="lines+markers",
                    line={
                        "color": "#F28E2B",
                        "width": 3,
                    },
                    marker={"size": 8},
                    customdata=saldos_formatados,
                    hovertemplate=(
                        "%{x}<br>"
                        "Saldo: %{customdata}"
                        "<extra></extra>"
                    ),
                ),
                secondary_y=False,
            )

            # Linha pontilhada: regressão linear do saldo dos meses fechados.
            if (
                inclinacao_tendencia is not None
                and not df_tendencia.empty
            ):
                tendencia_formatada = df_tendencia[
                    "tendencia_saldo"
                ].map(
                    lambda valor: (
                        f"R$ {_fmt_ptbr_num(valor, 2)}"
                    )
                )

                figura.add_trace(
                    go.Scatter(
                        x=df_tendencia["mes_label"],
                        y=df_tendencia["tendencia_saldo"],
                        name="Tendência do saldo",
                        mode="lines",
                        line={
                            "color": "#6B7280",
                            "width": 2,
                            "dash": "dash",
                        },
                        customdata=tendencia_formatada,
                        hovertemplate=(
                            "%{x}<br>"
                            "Tendência: %{customdata}"
                            "<extra></extra>"
                        ),
                    ),
                    secondary_y=False,
                )

            # Linha de giro: usa o eixo direito para permanecer legível ao lado
            # dos valores financeiros, que estão na escala dos milhões.
            figura.add_trace(
                go.Scatter(
                    x=df_evolucao["mes_label"],
                    y=df_evolucao["giro"],
                    name="Giro",
                    mode="lines+markers",
                    line={
                        "color": "#59A14F",
                        "width": 3,
                    },
                    marker={"size": 8},
                    customdata=giros_formatados,
                    hovertemplate=(
                        "%{x}<br>"
                        "Giro: %{customdata}"
                        "<extra></extra>"
                    ),
                ),
                secondary_y=True,
            )

            # A meta é representada no mesmo eixo do giro.
            figura.add_trace(
                go.Scatter(
                    x=df_evolucao["mes_label"],
                    y=[float(meta_giro)] * len(df_evolucao),
                    name=f"Meta de giro ({float(meta_giro):.2f})",
                    mode="lines",
                    line={
                        "color": "#E15759",
                        "width": 2,
                        "dash": "dot",
                    },
                    hovertemplate=(
                        "%{x}<br>"
                        f"Meta de giro: {float(meta_giro):.2f}"
                        "<extra></extra>"
                    ),
                ),
                secondary_y=True,
            )

            figura.update_layout(
                height=600,
                barmode="group",
                hovermode="closest",
                separators=",.",
                margin={
                    "l": 20,
                    "r": 20,
                    "t": 40,
                    "b": 20,
                },
                legend={
                    "orientation": "h",
                    "yanchor": "bottom",
                    "y": 1.02,
                    "xanchor": "left",
                    "x": 0,
                },
                xaxis_title="Mês",
            )

            figura.update_yaxes(
                title_text="Valores (R$)",
                rangemode="tozero",
                secondary_y=False,
            )

            figura.update_yaxes(
                title_text="Giro",
                rangemode="tozero",
                secondary_y=True,
            )

            st.plotly_chart(
                figura,
                width="stretch",
                key="grafico_evolucao_mensal_mast",
            )

            if df_evolucao["parcial"].any():
                st.caption(
                    "* Mês atual parcial. Ele aparece no gráfico e nos cards, "
                    "mas não participa do cálculo da tendência."
                )

            st.markdown("#### Dados mensais")

            # A tabela permite auditar os valores apresentados no gráfico.
            df_tabela = df_evolucao[
                [
                    "mes_ref",
                    "snapshot_date",
                    "entradas_val",
                    "saldo_val",
                    "giro",
                    "parcial",
                ]
            ].copy()

            df_tabela["snapshot_date"] = pd.to_datetime(
                df_tabela["snapshot_date"],
                errors="coerce",
            ).dt.strftime("%d/%m/%Y")

            df_tabela["parcial"] = df_tabela["parcial"].map(
                {
                    True: "Parcial",
                    False: "Fechado",
                }
            )

            df_tabela = df_tabela.rename(
                columns={
                    "mes_ref": "Mês",
                    "snapshot_date": "Último snapshot",
                    "entradas_val": "Entradas (R$)",
                    "saldo_val": "Saldo (R$)",
                    "giro": "Giro",
                    "parcial": "Situação",
                }
            )

            tabela_formatada = df_tabela.style.format(
                {
                    "Entradas (R$)": lambda valor: _fmt_ptbr_num(
                        valor,
                        2,
                    ),
                    "Saldo (R$)": lambda valor: _fmt_ptbr_num(
                        valor,
                        2,
                    ),
                    "Giro": lambda valor: (
                        ""
                        if pd.isna(valor)
                        else f"{float(valor):.2f}".replace(".", ",")
                    ),
                },
                na_rep="",
            )

            st.dataframe(
                tabela_formatada,
                width="stretch",
                hide_index=True,
            )

            st.caption(
                "Regras: Entradas = MB51 com débito/crédito S e ordem vazia; "
                "Saldo = último snapshot MAST do mês; "
                "Giro = Entradas ÷ Saldo."
            )
