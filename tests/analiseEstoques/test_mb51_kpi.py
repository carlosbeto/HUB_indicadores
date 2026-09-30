from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from analiseEstoques.scripts.update_from_sap import (
    compute_and_store_kpi_diario,
    ensure_dim_material_custo,
    ensure_kpi_diario_table,
    upsert_mb51_mov,
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


def criar_lote_mb51_para_upsert(
    movimentos: list[dict],
    custos: dict[str, float],
) -> tuple[sqlite3.Connection, pd.DataFrame]:
    """
    Prepara um banco isolado e um lote MB51 para testar a barreira de
    anomalias sem depender de arquivos Excel ou do banco operacional.
    """
    con = sqlite3.connect(":memory:")
    ensure_dim_material_custo(con)

    con.executemany(
        """
        INSERT INTO dim_material_custo (
            material,
            custo_unit,
            source_file,
            source_last_modified,
            load_ts
        )
        VALUES (?, ?, 'teste_custo.xlsx', '2026-09-30', '2026-09-30 08:00:00')
        """,
        list(custos.items()),
    )

    return con, pd.DataFrame(movimentos)


def movimento_mb51(
    *,
    material: str,
    quantidade: float,
    documento: str,
    item: str = "1",
) -> dict:
    """Monta uma linha normalizada no formato recebido pelo upsert."""
    return {
        "data_lancamento": "2026-09-29",
        "deposito": "MAST",
        "material": material,
        "deb_cred": "S",
        "ordem": "",
        "tipo_movimento": "Z69",
        "doc_deposito": "",
        "doc_material": documento,
        "item_doc_material": item,
        "descricao_mb51": "MATERIAL DE TESTE",
        "quantidade": quantidade,
    }


def test_upsert_mb51_permite_lote_dentro_dos_limites() -> None:
    """Uma carga operacional normal continua sendo gravada."""
    movimentos = [
        movimento_mb51(
            material="MAT001",
            quantidade=100.0,
            documento="4907000001",
        )
    ]
    con, df = criar_lote_mb51_para_upsert(
        movimentos,
        {"MAT001": 25.0},
    )

    try:
        upsert_mb51_mov(con, df, "mb51_normal.xlsx")

        row = con.execute(
            """
            SELECT quantidade, custo_unit, valor_estimado
            FROM fact_mb51_mov
            """
        ).fetchone()

        assert row == (100.0, 25.0, 2500.0)
    finally:
        con.close()


def test_upsert_mb51_bloqueia_quantidade_anomala_e_nao_grava_lote() -> None:
    """Uma quantidade anômala cancela inclusive as linhas normais do lote."""
    movimentos = [
        movimento_mb51(
            material="MAT_NORMAL",
            quantidade=10.0,
            documento="4907000002",
        ),
        movimento_mb51(
            material="MAT_ANOMALO",
            quantidade=100_001.0,
            documento="4907668093",
            item="7",
        ),
    ]
    con, df = criar_lote_mb51_para_upsert(
        movimentos,
        {"MAT_NORMAL": 5.0, "MAT_ANOMALO": 1.0},
    )

    try:
        with pytest.raises(ValueError) as erro:
            upsert_mb51_mov(con, df, "MB51MAST300926.xlsx")

        mensagem = str(erro.value)
        assert "Carga MB51 cancelada" in mensagem
        assert "Nenhum movimento deste lote foi gravado" in mensagem
        assert "MB51MAST300926.xlsx" in mensagem
        assert "material=MAT_ANOMALO" in mensagem
        assert "documento=4907668093" in mensagem
        assert "item=7" in mensagem
        assert "quantidade=100,001.00" in mensagem

        total = con.execute(
            "SELECT COUNT(*) FROM fact_mb51_mov"
        ).fetchone()[0]
        assert total == 0
    finally:
        con.close()


def test_upsert_mb51_bloqueia_valor_estimado_anomalo() -> None:
    """Valor excessivo também bloqueia a carga, mesmo com pouca quantidade."""
    movimentos = [
        movimento_mb51(
            material="MAT_CARO",
            quantidade=1.0,
            documento="4907668284",
            item="3",
        )
    ]
    con, df = criar_lote_mb51_para_upsert(
        movimentos,
        {"MAT_CARO": 10_000_001.0},
    )

    try:
        with pytest.raises(ValueError) as erro:
            upsert_mb51_mov(con, df, "mb51_valor_anomalo.xlsx")

        mensagem = str(erro.value)
        assert "material=MAT_CARO" in mensagem
        assert "documento=4907668284" in mensagem
        assert "valor_estimado=10,000,001.00" in mensagem

        total = con.execute(
            "SELECT COUNT(*) FROM fact_mb51_mov"
        ).fetchone()[0]
        assert total == 0
    finally:
        con.close()
