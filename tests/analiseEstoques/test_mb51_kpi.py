from __future__ import annotations

import sqlite3
from datetime import date

from analiseEstoques.scripts.update_from_sap import (
    compute_and_store_kpi_diario,
    ensure_kpi_diario_table,
)


def criar_banco_teste() -> sqlite3.Connection:
    """
    Cria um banco SQLite em memória com somente as estruturas
    necessárias para testar a regra de negócio da MB51.

    Regra oficial protegida pelo teste:
    - Entrada real: S com ordem vazia.
    - Saída real: todo H, independentemente de ordem.
    """

    con = sqlite3.connect(":memory:")

    con.execute(
        """
        CREATE TABLE fact_estoque_snapshot (
            snapshot_date TEXT NOT NULL,
            deposito TEXT NOT NULL,
            material TEXT NOT NULL,
            qtd_total REAL,
            val_total REAL
        )
        """
    )

    con.execute(
        """
        CREATE TABLE fact_mb51_mov (
            data_lancamento TEXT NOT NULL,
            deposito TEXT NOT NULL,
            material TEXT NOT NULL,
            deb_cred TEXT NOT NULL,
            ordem TEXT,
            quantidade REAL,
            valor_estimado REAL
        )
        """
    )

    ensure_kpi_diario_table(con)

    return con


def test_kpi_mb51_mast_respeita_regra_de_entradas_e_saidas() -> None:
    """
    Confirma a regra oficial da MB51 para o MAST.

    Entradas:
    - S sem ordem entra.
    - S com ordem não entra.

    Saídas:
    - H sem ordem entra.
    - H com ordem entra.
    """

    con = criar_banco_teste()

    try:
        # Snapshot necessário para o cálculo diário.
        con.execute(
            """
            INSERT INTO fact_estoque_snapshot (
                snapshot_date,
                deposito,
                material,
                qtd_total,
                val_total
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-08-25", "MAST", "MAT001", 100.0, 1000.0),
        )

        movimentos = [
            # Entrada válida: S sem ordem.
            ("2026-08-25", "MAST", "MAT001", "S", "", 10.0, 100.0),

            # Entrada inválida para o KPI: S com ordem.
            ("2026-08-25", "MAST", "MAT002", "S", "OP001", 20.0, 200.0),

            # Saída válida: H sem ordem.
            ("2026-08-25", "MAST", "MAT003", "H", "", 30.0, 300.0),

            # Saída válida: H com ordem.
            ("2026-08-25", "MAST", "MAT004", "H", "OP002", 40.0, 400.0),
        ]

        con.executemany(
            """
            INSERT INTO fact_mb51_mov (
                data_lancamento,
                deposito,
                material,
                deb_cred,
                ordem,
                quantidade,
                valor_estimado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            movimentos,
        )

        compute_and_store_kpi_diario(
            con,
            "MAST",
            date(2026, 8, 25),
        )

        row = con.execute(
            """
            SELECT
                entradas_mb51_val,
                entradas_mb51_qtd,
                saidas_mb51_val,
                saidas_mb51_qtd,
                net_val,
                net_qtd
            FROM kpi_diario_deposito
            WHERE snapshot_date = ?
              AND deposito = ?
            """,
            ("2026-08-25", "MAST"),
        ).fetchone()

        assert row is not None

        (
            entradas_val,
            entradas_qtd,
            saidas_val,
            saidas_qtd,
            net_val,
            net_qtd,
        ) = row

        # Apenas S sem ordem.
        assert entradas_val == 100.0
        assert entradas_qtd == 10.0

        # Todo H, com ou sem ordem.
        assert saidas_val == 700.0
        assert saidas_qtd == 70.0

        # Consumo líquido = saídas - entradas.
        assert net_val == 600.0
        assert net_qtd == 60.0

    finally:
        con.close()