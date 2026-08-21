# code/analiseInventarios/scripts/02_load_mm_snapshot.py
# -*- coding: utf-8 -*-

"""
Atualiza a tabela mm_snapshot com a foto mais recente dos depósitos MM.

Fonte oficial:
    data/analiseEstoques/SAP_IN/Materiais*.xlsx

Responsabilidade:
- utilizar o arquivo Materiais*.xlsx cronologicamente mais recente;
- considerar somente os depósitos MAST e MASR;
- consolidar quantidade e valor de:
    utilização livre + qualidade + bloqueado;
- gravar a foto atual na tabela mm_snapshot.

A pasta legada MM_SNAPSHOT_IN não participa mais deste fluxo.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from analiseInventarios.scripts.materiais_snapshot import (
    choose_latest_file,
    get_snapshot_info_from_filename,
    list_material_files,
    read_material_excel,
    to_float_ptbr,
)


# ------------------------------------------------------------
# CAMINHOS
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data_db" / "inventarios.sqlite"


# ------------------------------------------------------------
# CONFIGURAÇÃO
# ------------------------------------------------------------
MM_DEPOSITOS = {"MAST", "MASR"}


# ------------------------------------------------------------
# TRANSFORMAÇÃO
# ------------------------------------------------------------
def transform_mm_snapshot_df(
    df: pd.DataFrame,
    file_path: Path,
) -> pd.DataFrame:
    """
    Converte o Materiais*.xlsx para o formato necessário em mm_snapshot.
    """

    snapshot_date, _ = get_snapshot_info_from_filename(file_path)

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

    # --------------------------------------------------------
    # Limpeza das chaves
    # --------------------------------------------------------
    df["material"] = (
        df["material"]
        .astype(str)
        .str.strip()
    )

    df["material_desc"] = (
        df["material_desc"]
        .astype(str)
        .str.strip()
    )

    df["warehouse_code"] = (
        df["warehouse_code"]
        .astype(str)
        .str.strip()
    )

    # Mantém somente os depósitos MM.
    df = df[
        df["warehouse_code"].isin(MM_DEPOSITOS)
    ].copy()

    # Remove linhas sem material válido.
    df = df[
        (df["material"] != "")
        & (df["material"].str.lower() != "nan")
    ].copy()

    # --------------------------------------------------------
    # Conversões numéricas
    # --------------------------------------------------------
    qty_cols = [
        "qty_unrestricted",
        "qty_quality",
        "qty_blocked",
    ]

    value_cols = [
        "value_unrestricted",
        "value_quality",
        "value_blocked",
    ]

    for col in qty_cols:
        df[col] = (
            df[col]
            .apply(to_float_ptbr)
            .fillna(0.0)
        )

    for col in value_cols:
        df[col] = (
            df[col]
            .apply(to_float_ptbr)
            .fillna(0.0)
        )

    # --------------------------------------------------------
    # Totais
    # --------------------------------------------------------
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

    # Mantém apenas materiais com presença real de estoque.
    df = df[
        (df["qty_total"] > 0)
        | (df["value_total"] > 0)
    ].copy()

    # --------------------------------------------------------
    # Metadados
    # --------------------------------------------------------
    df["snapshot_date"] = snapshot_date
    df["file_name"] = file_path.name
    df["loaded_at"] = datetime.now().isoformat(
        timespec="seconds"
    )

    # O relatório Materiais*.xlsx atual não possui estes campos.
    # Mantemos as colunas como NULL apenas por compatibilidade
    # com o schema histórico de mm_snapshot.
    df["plant"] = None
    df["umb"] = None
    df["tmat"] = None

    cols = [
        "snapshot_date",
        "plant",
        "warehouse_code",
        "material",
        "material_desc",
        "umb",
        "qty_unrestricted",
        "qty_blocked",
        "qty_total",
        "value_unrestricted",
        "value_blocked",
        "value_total",
        "tmat",
        "file_name",
        "loaded_at",
    ]

    return df[cols]


# ------------------------------------------------------------
# PERSISTÊNCIA
# ------------------------------------------------------------
def load_latest_mm_snapshot(
    conn: sqlite3.Connection,
    file_path: Path,
) -> tuple[str, int]:
    """
    Carrega na tabela mm_snapshot a foto MM mais recente disponível.
    """

    df_raw = read_material_excel(file_path)

    df = transform_mm_snapshot_df(
        df_raw,
        file_path,
    )

    if df.empty:
        raise RuntimeError(
            f"Nenhum material MAST/MASR encontrado em {file_path.name}"
        )

    snapshot_date = str(
        df["snapshot_date"].iloc[0]
    )

    rows = list(
        df.itertuples(
            index=False,
            name=None,
        )
    )

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO mm_snapshot (
                snapshot_date,
                plant,
                warehouse_code,
                material,
                material_desc,
                umb,
                qty_unrestricted,
                qty_blocked,
                qty_total,
                value_unrestricted,
                value_blocked,
                value_total,
                tmat,
                file_name,
                loaded_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            );
            """,
            rows,
        )

    return snapshot_date, len(rows)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main() -> None:
    files = list_material_files()

    latest_file = choose_latest_file(files)

    snapshot_date, _ = get_snapshot_info_from_filename(
        latest_file
    )

    print(
        "[INFO] Snapshot MM selecionado | "
        f"arquivo={latest_file.name} | "
        f"data={snapshot_date}"
    )

    with sqlite3.connect(DB_PATH) as conn:
        loaded_date, row_count = (
            load_latest_mm_snapshot(
                conn,
                latest_file,
            )
        )

    print(
        "[OK] mm_snapshot atualizado | "
        f"data={loaded_date} | "
        f"arquivo={latest_file.name} | "
        f"linhas={row_count}"
    )


if __name__ == "__main__":
    main()
