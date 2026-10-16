from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analiseEstoques.scripts.streamlit_app import (
    load_evolucao_mensal_mast,
)


def _criar_banco_de_teste(caminho: Path) -> None:
    """
    Cria um banco SQLite mínimo para testar a evolução mensal.

    Os dados são sintéticos e permitem verificar:
    - escolha do último snapshot do mês;
    - regra de entrada S com ordem vazia;
    - exclusão opcional dos movimentos 343/344;
    - cálculo do giro financeiro.
    """

    with sqlite3.connect(caminho) as connection:
        connection.executescript(
            """
            CREATE TABLE fact_estoque_snapshot (
                deposito TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                qtd_total REAL,
                val_total REAL
            );

            CREATE TABLE fact_mb51_mov (
                deposito TEXT NOT NULL,
                data_lancamento TEXT NOT NULL,
                deb_cred TEXT,
                ordem TEXT,
                tipo_movimento TEXT,
                valor_estimado REAL
            );
            """
        )

        # Janeiro possui dois snapshots. O teste deve utilizar somente
        # o snapshot mais recente, de 31/01, cujo saldo total é 100.
        connection.executemany(
            """
            INSERT INTO fact_estoque_snapshot (
                deposito,
                snapshot_date,
                qtd_total,
                val_total
            )
            VALUES (?, ?, ?, ?);
            """,
            [
                ("MAST", "2026-01-10", 10.0, 500.0),
                ("MAST", "2026-01-31", 2.0, 60.0),
                ("MAST", "2026-01-31", 3.0, 40.0),
                ("MAST", "2026-02-28", 5.0, 200.0),
                # Outro depósito não pode interferir no MAST.
                ("MASR", "2026-01-31", 1.0, 999.0),
            ],
        )

        connection.executemany(
            """
            INSERT INTO fact_mb51_mov (
                deposito,
                data_lancamento,
                deb_cred,
                ordem,
                tipo_movimento,
                valor_estimado
            )
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            [
                # Entrada válida de janeiro.
                ("MAST", "2026-01-05", "S", "", "101", 120.0),

                # Movimento 343: entra somente quando o filtro estiver desligado.
                ("MAST", "2026-01-15", "S", "", "343", 20.0),

                # Ordem preenchida: não atende à regra de entrada do BI.
                ("MAST", "2026-01-20", "S", "ORDEM-1", "101", 700.0),

                # Crédito H: não atende à regra de entrada do BI.
                ("MAST", "2026-01-25", "H", "", "201", 300.0),

                # Entrada válida de fevereiro.
                ("MAST", "2026-02-10", "S", "", "101", 240.0),

                # Outro depósito não pode interferir no MAST.
                ("MASR", "2026-01-05", "S", "", "101", 999.0),
            ],
        )


def test_evolucao_usa_ultimo_snapshot_e_regra_de_entrada(
    tmp_path: Path,
) -> None:
    banco = tmp_path / "estoque_teste.sqlite"
    _criar_banco_de_teste(banco)

    resultado = load_evolucao_mensal_mast(
        str(banco),
        ("2026-01", "2026-02"),
        False,
    )

    assert resultado["mes_ref"].tolist() == [
        "2026-01",
        "2026-02",
    ]

    assert resultado["snapshot_date"].tolist() == [
        "2026-01-31",
        "2026-02-28",
    ]

    # Janeiro: entradas 120 + 20 do movimento 343.
    # Saldo: 60 + 40 do último snapshot.
    assert resultado.loc[0, "entradas_val"] == pytest.approx(140.0)
    assert resultado.loc[0, "saldo_val"] == pytest.approx(100.0)
    assert resultado.loc[0, "giro"] == pytest.approx(1.4)

    # Fevereiro: entrada 240 e saldo 200.
    assert resultado.loc[1, "entradas_val"] == pytest.approx(240.0)
    assert resultado.loc[1, "saldo_val"] == pytest.approx(200.0)
    assert resultado.loc[1, "giro"] == pytest.approx(1.2)


def test_evolucao_respeita_exclusao_dos_movimentos_343_344(
    tmp_path: Path,
) -> None:
    banco = tmp_path / "estoque_teste.sqlite"
    _criar_banco_de_teste(banco)

    resultado = load_evolucao_mensal_mast(
        str(banco),
        ("2026-01",),
        True,
    )

    # Com o filtro ligado, a entrada 343 de R$ 20 é retirada.
    assert resultado.loc[0, "entradas_val"] == pytest.approx(120.0)
    assert resultado.loc[0, "saldo_val"] == pytest.approx(100.0)
    assert resultado.loc[0, "giro"] == pytest.approx(1.2)