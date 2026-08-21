# code/analiseInventarios/scripts/load_baseline_snapshot.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from analiseInventarios.scripts.materiais_snapshot import (
    SAP_IN_DIR,
    choose_first_file_per_month,
    get_snapshot_info_from_filename,
    list_material_files,
    read_material_excel,
    to_float_ptbr,
)


# ------------------------------------------------------------
# CAMINHOS DO PROJETO
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data_db" / "inventarios.sqlite"

# A fonte do baseline é o mesmo SAP_IN diário utilizado pelo HUB.
# O caminho é resolvido dinamicamente para DEV ou PROD.
BASELINE_DIR = SAP_IN_DIR

# ------------------------------------------------------------
# CONSULTAS AO BANCO
# ------------------------------------------------------------

def get_existing_snapshot_months(
    conn: sqlite3.Connection,
) -> set[str]:
    """
    Retorna os meses já carregados na tabela baseline_items.

    Essa verificação evita carregar novamente um mês que já possui
    baseline registrado no banco.
    """

    rows = conn.execute(
        """
        SELECT DISTINCT snapshot_month
        FROM baseline_items
        ORDER BY snapshot_month
        """
    ).fetchall()

    return {
        str(row[0])
        for row in rows
        if row[0] is not None
    }

# ------------------------------------------------------------
# TRANSFORMAÇÃO DO BASELINE
# ------------------------------------------------------------

def transform_baseline_df(df: pd.DataFrame, file_path: Path) -> pd.DataFrame:
    """
    Padroniza o DataFrame para o schema da tabela baseline_items.
    """
    snapshot_date, snapshot_month = get_snapshot_info_from_filename(file_path)

    df = df.rename(
        columns={
            "Material": "material",
            "Descrição de material": "material_desc",
            "Depósito": "warehouse_code",
            "Estoque de utilização livre": "qty_unrestricted",
            "Estoque em controle de qualidade": "qty_quality",
            "Estoque bloqueado": "qty_blocked",
            "Valor do estoque de utilização livre": "value_unrestricted",
            "Valor do estoque no controle de qualidade": "value_quality",
            "Valor do estoque bloqueado": "value_blocked",
        }
    ).copy()

    # Conversões numéricas robustas
    for col in ["qty_unrestricted", "qty_quality", "qty_blocked"]:
        df[col] = df[col].apply(to_float_ptbr).fillna(0.0)

    for col in ["value_unrestricted", "value_quality", "value_blocked"]:
        df[col] = df[col].apply(to_float_ptbr).fillna(0.0)

    # Totais
    df["qty_total"] = (
        df["qty_unrestricted"]
        + df["qty_quality"]
        + df["qty_blocked"]
    )

    df["value_total"] = (
        df["value_unrestricted"]
        + df["value_quality"]
        + df["value_blocked"]
    )

    # Metadados
    df["snapshot_date"] = snapshot_date
    df["snapshot_month"] = snapshot_month
    df["source_file"] = file_path.name
    df["loaded_at"] = datetime.now().isoformat(timespec="seconds")

    # Limpeza de texto
    df["material"] = df["material"].astype(str).str.strip()
    df["material_desc"] = df["material_desc"].astype(str).str.strip()
    df["warehouse_code"] = df["warehouse_code"].astype(str).str.strip()

    # Remove linhas sem material ou depósito
    df = df[
        (df["material"] != "")
        & (df["material"].str.lower() != "nan")
        & (df["warehouse_code"] != "")
        & (df["warehouse_code"].str.lower() != "nan")
    ].copy()

    # Mantemos apenas itens que tenham alguma presença no estoque
    # (quantidade ou valor)
    df = df[
        (df["qty_total"] > 0) | (df["value_total"] > 0)
    ].copy()

    cols = [
        "snapshot_date",
        "snapshot_month",
        "warehouse_code",
        "material",
        "material_desc",
        "qty_unrestricted",
        "qty_quality",
        "qty_blocked",
        "qty_total",
        "value_unrestricted",
        "value_quality",
        "value_blocked",
        "value_total",
        "source_file",
        "loaded_at",
    ]

    return df[cols]


def load_month_if_missing(conn: sqlite3.Connection, file_path: Path) -> tuple[str, int]:
    """
    Carrega um arquivo de baseline na tabela baseline_items.
    Retorna:
    - snapshot_month carregado
    - quantidade de linhas inseridas
    """
    df_raw = read_material_excel(file_path)
    df = transform_baseline_df(df_raw, file_path)

    snapshot_month = str(df["snapshot_month"].iloc[0])

    df.to_sql(
        "baseline_items",
        conn,
        if_exists="append",
        index=False,
    )

    return snapshot_month, len(df)

def main() -> None:
    files = list_material_files()
    first_files_by_month = choose_first_file_per_month(files)

    with sqlite3.connect(DB_PATH) as conn:
        existing_months = get_existing_snapshot_months(conn)

        months_loaded = []
        months_skipped = []

        for snapshot_month in sorted(first_files_by_month.keys()):
            file_path = first_files_by_month[snapshot_month]

            if snapshot_month in existing_months:
                months_skipped.append((snapshot_month, file_path.name))
                print(f"[SKIP] baseline_items | mês já existe | {snapshot_month} | arquivo={file_path.name}")
                continue

            loaded_month, row_count = load_month_if_missing(conn, file_path)
            months_loaded.append((loaded_month, file_path.name, row_count))
            print(f"[OK] baseline_items | mês={loaded_month} | arquivo={file_path.name} | linhas={row_count}")

    print("\n[DONE] Carga de baseline mensal finalizada.")

    if months_loaded:
        print("[RESUMO] Meses carregados:")
        for month, file_name, row_count in months_loaded:
            print(f"  - {month} | {file_name} | linhas={row_count}")

    if months_skipped:
        print("[RESUMO] Meses ignorados (já existentes):")
        for month, file_name in months_skipped:
            print(f"  - {month} | {file_name}")


if __name__ == "__main__":
    main()