from __future__ import annotations

import sqlite3
from datetime import date

from analiseEstoques.scripts.update_from_sap import ensure_baseline


def criar_banco_teste() -> sqlite3.Connection:
    """
    Cria um SQLite em memória com a estrutura mínima dos snapshots.

    A tabela baseline_mensal será criada pela própria ensure_baseline().
    """

    con = sqlite3.connect(":memory:")

    con.execute(
        """
        CREATE TABLE fact_estoque_snapshot (
            snapshot_date TEXT NOT NULL,
            deposito TEXT NOT NULL,
            material TEXT NOT NULL,
            qtd_total REAL,
            val_total REAL,
            source_file TEXT,
            load_ts TEXT,
            PRIMARY KEY (
                snapshot_date,
                deposito,
                material
            )
        )
        """
    )

    return con


def inserir_snapshot(
    con: sqlite3.Connection,
    snapshot_date: str,
    deposito: str,
    material: str,
    qtd_total: float,
    val_total: float,
    source_file: str,
) -> None:
    """Inclui uma posição de material na fotografia de estoque."""

    con.execute(
        """
        INSERT INTO fact_estoque_snapshot (
            snapshot_date,
            deposito,
            material,
            qtd_total,
            val_total,
            source_file,
            load_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_date,
            deposito,
            material,
            qtd_total,
            val_total,
            source_file,
            f"{snapshot_date} 08:00:00",
        ),
    )


def obter_baseline(
    con: sqlite3.Connection,
    mes_ref: str,
    deposito: str,
) -> sqlite3.Row | None:
    """Consulta o baseline criado pelo teste."""

    con.row_factory = sqlite3.Row

    return con.execute(
        """
        SELECT
            mes_ref,
            deposito,
            baseline_date,
            qtd_base_total,
            val_base_total,
            source_file
        FROM baseline_mensal
        WHERE mes_ref = ?
          AND deposito = ?
        """,
        (mes_ref, deposito),
    ).fetchone()


def test_baseline_usa_ultimo_snapshot_do_mes_anterior() -> None:
    """
    O fechamento do mês anterior deve ser o ponto inicial do mês atual.
    """

    con = criar_banco_teste()

    try:
        inserir_snapshot(
            con,
            "2026-08-30",
            "MAST",
            "MAT001",
            10.0,
            100.0,
            "snapshot_20260830.xlsx",
        )
        inserir_snapshot(
            con,
            "2026-08-31",
            "MAST",
            "MAT001",
            8.0,
            80.0,
            "snapshot_20260831.xlsx",
        )
        inserir_snapshot(
            con,
            "2026-08-31",
            "MAST",
            "MAT002",
            12.0,
            120.0,
            "snapshot_20260831.xlsx",
        )

        # Snapshot do mês atual não deve substituir o fechamento anterior.
        inserir_snapshot(
            con,
            "2026-09-01",
            "MAST",
            "MAT001",
            7.0,
            70.0,
            "snapshot_20260901.xlsx",
        )

        criado = ensure_baseline(
            con,
            "MAST",
            date(2026, 9, 1),
            "snapshot_20260901.xlsx",
        )

        baseline = obter_baseline(con, "2026-09", "MAST")

        assert criado is True
        assert baseline is not None
        assert baseline["baseline_date"] == "2026-08-31"
        assert baseline["qtd_base_total"] == 20.0
        assert baseline["val_base_total"] == 200.0
        assert baseline["source_file"] == "snapshot_20260831.xlsx"

    finally:
        con.close()


def test_baseline_funciona_na_virada_do_ano() -> None:
    """
    Janeiro deve herdar o último fechamento disponível de dezembro.
    """

    con = criar_banco_teste()

    try:
        inserir_snapshot(
            con,
            "2026-12-31",
            "MAST",
            "MAT001",
            25.0,
            250.0,
            "snapshot_20261231.xlsx",
        )
        inserir_snapshot(
            con,
            "2027-01-04",
            "MAST",
            "MAT001",
            20.0,
            200.0,
            "snapshot_20270104.xlsx",
        )

        criado = ensure_baseline(
            con,
            "MAST",
            date(2027, 1, 4),
            "snapshot_20270104.xlsx",
        )

        baseline = obter_baseline(con, "2027-01", "MAST")

        assert criado is True
        assert baseline is not None
        assert baseline["baseline_date"] == "2026-12-31"
        assert baseline["qtd_base_total"] == 25.0
        assert baseline["val_base_total"] == 250.0
        assert baseline["source_file"] == "snapshot_20261231.xlsx"

    finally:
        con.close()


def test_baseline_usa_primeiro_snapshot_atual_sem_fechamento_anterior() -> None:
    """
    Sem histórico anterior, utiliza o primeiro snapshot disponível no mês.
    Essa é a contingência necessária para o primeiro mês da série.
    """

    con = criar_banco_teste()

    try:
        inserir_snapshot(
            con,
            "2026-01-02",
            "MAST",
            "MAT001",
            30.0,
            300.0,
            "snapshot_20260102.xlsx",
        )
        inserir_snapshot(
            con,
            "2026-01-05",
            "MAST",
            "MAT001",
            28.0,
            280.0,
            "snapshot_20260105.xlsx",
        )

        criado = ensure_baseline(
            con,
            "MAST",
            date(2026, 1, 5),
            "snapshot_20260105.xlsx",
        )

        baseline = obter_baseline(con, "2026-01", "MAST")

        assert criado is True
        assert baseline is not None
        assert baseline["baseline_date"] == "2026-01-02"
        assert baseline["qtd_base_total"] == 30.0
        assert baseline["val_base_total"] == 300.0
        assert baseline["source_file"] == "snapshot_20260102.xlsx"

    finally:
        con.close()


def test_baseline_existente_nao_e_sobrescrito() -> None:
    """Uma nova execução não pode alterar um baseline já registrado."""

    con = criar_banco_teste()

    try:
        inserir_snapshot(
            con,
            "2026-08-31",
            "MAST",
            "MAT001",
            10.0,
            100.0,
            "snapshot_20260831.xlsx",
        )

        primeiro_resultado = ensure_baseline(
            con,
            "MAST",
            date(2026, 9, 1),
            "snapshot_20260901.xlsx",
        )

        inserir_snapshot(
            con,
            "2026-08-31",
            "MAST",
            "MAT002",
            90.0,
            900.0,
            "snapshot_correcao_20260831.xlsx",
        )

        segundo_resultado = ensure_baseline(
            con,
            "MAST",
            date(2026, 9, 2),
            "snapshot_20260902.xlsx",
        )

        baseline = obter_baseline(con, "2026-09", "MAST")

        assert primeiro_resultado is True
        assert segundo_resultado is False
        assert baseline is not None
        assert baseline["qtd_base_total"] == 10.0
        assert baseline["val_base_total"] == 100.0

    finally:
        con.close()


def test_baseline_nao_e_criado_sem_snapshot() -> None:
    """Sem fechamento anterior ou snapshot atual, não cria valor vazio."""

    con = criar_banco_teste()

    try:
        criado = ensure_baseline(
            con,
            "MAST",
            date(2026, 10, 1),
            "arquivo_sem_snapshot.xlsx",
        )

        quantidade = con.execute(
            """
            SELECT COUNT(*)
            FROM baseline_mensal
            WHERE mes_ref = '2026-10'
              AND deposito = 'MAST'
            """
        ).fetchone()[0]

        assert criado is False
        assert quantidade == 0

    finally:
        con.close()