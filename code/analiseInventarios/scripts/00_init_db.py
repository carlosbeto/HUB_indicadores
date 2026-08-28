# code/analiseInventarios/scripts/00_init_db.py
# -*- coding: utf-8 -*-

"""
Inicialização do banco SQLite do módulo de Inventários.

Responsabilidade:
- criar as tabelas estruturais necessárias;
- criar os índices utilizados pelas consultas;
- criar a view auxiliar v_docs;
- permitir reconstrução do schema a partir de um banco vazio.

O script é idempotente:
executá-lo novamente não remove os dados existentes das tabelas.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


# ------------------------------------------------------------
# CAMINHOS
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    PROJECT_ROOT
    / "data_db"
    / "inventarios.sqlite"
)


# ------------------------------------------------------------
# SCHEMA
# ------------------------------------------------------------
SCHEMA = """
PRAGMA foreign_keys = ON;


-- ============================================================
-- CONTAGENS DE INVENTÁRIO MM / EWM
-- ============================================================
CREATE TABLE IF NOT EXISTS counts (
    row_uid TEXT PRIMARY KEY,

    source_system TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    item_key TEXT NOT NULL,

    inv_doc TEXT NOT NULL,
    inv_item TEXT NOT NULL,
    material TEXT NOT NULL,
    warehouse_code TEXT NOT NULL,
    logical_warehouse TEXT,

    count_date TEXT,
    qty_recorded REAL,
    qty_counted REAL,
    qty_diff REAL,
    value_diff REAL,

    status TEXT,
    counted_by TEXT,

    storage_area TEXT,
    bin_location TEXT,
    stock_type TEXT,
    wh_order TEXT,

    -- Método de inventário físico informado pelo EWM.
    -- Mantemos o código original do SAP (HS / HL) para preservar
    -- o significado da fonte. Para inventários MM, permanece NULL.
    count_method TEXT,

    year_iso INTEGER,
    week_iso INTEGER,
    week_start TEXT,
    week_end TEXT,

    file_name TEXT NOT NULL,
    loaded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_counts_week
ON counts (
    year_iso,
    week_iso,
    warehouse_code,
    source_system
);

CREATE INDEX IF NOT EXISTS ix_counts_doc
ON counts (
    source_system,
    inv_doc
);

CREATE INDEX IF NOT EXISTS ix_counts_material
ON counts (
    material,
    warehouse_code,
    source_system
);


-- ============================================================
-- FOTO ATUAL DOS DEPÓSITOS MM
-- ============================================================
CREATE TABLE IF NOT EXISTS mm_snapshot (
    snapshot_date TEXT NOT NULL,
    plant TEXT,
    warehouse_code TEXT NOT NULL,
    material TEXT NOT NULL,
    material_desc TEXT,
    umb TEXT,

    qty_unrestricted REAL,
    qty_blocked REAL,
    qty_total REAL,

    value_unrestricted REAL,
    value_blocked REAL,
    value_total REAL,

    tmat TEXT,
    file_name TEXT NOT NULL,
    loaded_at TEXT NOT NULL,

    PRIMARY KEY (
        snapshot_date,
        warehouse_code,
        material
    )
);

CREATE INDEX IF NOT EXISTS ix_mm_snapshot_dep
ON mm_snapshot (
    warehouse_code,
    snapshot_date
);


-- ============================================================
-- BASELINE MENSAL DOS DEPÓSITOS
-- ============================================================
CREATE TABLE IF NOT EXISTS baseline_items (
    snapshot_date TEXT NOT NULL,
    snapshot_month TEXT NOT NULL,
    warehouse_code TEXT NOT NULL,
    material TEXT NOT NULL,
    material_desc TEXT,

    qty_unrestricted REAL,
    qty_quality REAL,
    qty_blocked REAL,
    qty_total REAL,

    value_unrestricted REAL,
    value_quality REAL,
    value_blocked REAL,
    value_total REAL,

    source_file TEXT,
    loaded_at TEXT NOT NULL,

    PRIMARY KEY (
        snapshot_date,
        warehouse_code,
        material
    )
);

CREATE INDEX IF NOT EXISTS idx_baseline_items_material
ON baseline_items (
    material
);

CREATE INDEX IF NOT EXISTS idx_baseline_items_month
ON baseline_items (
    snapshot_month
);

CREATE INDEX IF NOT EXISTS idx_baseline_items_wh
ON baseline_items (
    warehouse_code
);


-- ============================================================
-- VIEW AUXILIAR DE DOCUMENTOS DE INVENTÁRIO
-- ============================================================
DROP VIEW IF EXISTS v_docs;

CREATE VIEW v_docs AS
SELECT
    source_system,
    warehouse_code,
    inv_doc,
    doc_key,
    year_iso,
    week_iso,

    COUNT(*) AS item_lines,
    COUNT(DISTINCT material) AS materials_distinct,
    SUM(COALESCE(qty_diff, 0)) AS diff_total

FROM counts

GROUP BY
    source_system,
    warehouse_code,
    inv_doc,
    doc_key,
    year_iso,
    week_iso;
"""

def ensure_counts_logical_warehouse(
    conn: sqlite3.Connection,
) -> None:
    """
    Garante a existência da coluna logical_warehouse em counts.

    Compatibilidade:
    - bancos novos já recebem a coluna pelo CREATE TABLE;
    - bancos existentes recebem a coluna via ALTER TABLE;
    - registros MM existentes usam o próprio warehouse_code;
    - todo o histórico EWM atual é classificado como WEPV.

    O preenchimento de EWM como WEPV é seguro para o histórico atual,
    pois os arquivos EWM existentes foram previamente auditados e
    pertencem exclusivamente ao WEPV.
    """

    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(counts)").fetchall()
    }

    if "logical_warehouse" not in columns:
        conn.execute(
            """
            ALTER TABLE counts
            ADD COLUMN logical_warehouse TEXT
            """
        )

    # MM: warehouse_code já representa o depósito lógico
    # (MAST / MASR).
    conn.execute(
        """
        UPDATE counts
        SET logical_warehouse = warehouse_code
        WHERE source_system = 'MM'
          AND (
              logical_warehouse IS NULL
              OR TRIM(logical_warehouse) = ''
          )
        """
    )

    # Histórico EWM existente: todos os registros atuais foram
    # comprovadamente originados do WEPV.
    conn.execute(
        """
        UPDATE counts
        SET logical_warehouse = 'WEPV'
        WHERE source_system = 'EWM'
          AND (
              logical_warehouse IS NULL
              OR TRIM(logical_warehouse) = ''
          )
        """
    )


def ensure_counts_count_method(
    conn: sqlite3.Connection,
) -> None:
    """
    Garante a existência da coluna count_method em counts.

    Compatibilidade:
    - bancos novos já recebem a coluna pelo CREATE TABLE;
    - bancos existentes recebem a coluna via ALTER TABLE;
    - o método é um atributo da contagem e não participa das chaves;
    - registros históricos permanecem NULL até serem reprocessados
      a partir de uma fonte EWM que contenha HS / HL.

    Não fazemos backfill presumido nesta migração porque o método deve
    sempre vir da informação oficial registrada no relatório SAP EWM.
    """

    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(counts)").fetchall()
    }

    if "count_method" not in columns:
        conn.execute(
            """
            ALTER TABLE counts
            ADD COLUMN count_method TEXT
            """
        )


# ------------------------------------------------------------
# INICIALIZAÇÃO
# ------------------------------------------------------------
def initialize_database(
    db_path: Path,
) -> None:
    """
    Garante que o banco informado possua o schema de Inventários.

    Pode ser utilizado tanto pelo banco operacional quanto por testes
    realizados sobre bancos temporários.
    """

    db_path = Path(db_path)

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        ensure_counts_logical_warehouse(conn)
        ensure_counts_count_method(conn)
        conn.commit()


def main() -> None:
    initialize_database(DB_PATH)

    print(
        f"[OK] Schema de Inventários garantido em: {DB_PATH}"
    )


if __name__ == "__main__":
    main()