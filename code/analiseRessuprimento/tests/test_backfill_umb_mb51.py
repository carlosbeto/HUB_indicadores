from __future__ import annotations

"""Testes do retropreenchimento da UMB nos movimentos históricos."""

import sqlite3
import unittest

import pandas as pd

from etl.backfill_umb_mb51 import (
    preparar_unidades,
    retropreencher_unidades,
)


class TestBackfillUmbMb51(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE fact_mb51_movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                documento_material TEXT NOT NULL,
                item_documento TEXT NOT NULL,
                quantidade REAL NOT NULL,
                unidade_medida_basica TEXT,
                UNIQUE (documento_material, item_documento)
            );

            INSERT INTO fact_mb51_movimentos (
                documento_material,
                item_documento,
                quantidade
            )
            VALUES
                ('500000001', '1', -20),
                ('500000002', '1', -5);
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    @staticmethod
    def _snapshot() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Doc.material": 500000001,
                    "Item doc.material": 1,
                    "UMB": "PEÇ",
                },
                {
                    "Doc.material": 500000002,
                    "Item doc.material": 1,
                    "UMB": "KG",
                },
            ]
        )

    def test_retropreenche_movimentos_existentes(self) -> None:
        unidades = preparar_unidades(self._snapshot())

        atualizadas = retropreencher_unidades(self.conn, unidades)

        registros = self.conn.execute(
            """
            SELECT documento_material, unidade_medida_basica
            FROM fact_mb51_movimentos
            ORDER BY documento_material;
            """
        ).fetchall()

        self.assertEqual(atualizadas, 2)
        self.assertEqual(
            registros,
            [("500000001", "PEÇ"), ("500000002", "KG")],
        )

    def test_segunda_execucao_e_idempotente(self) -> None:
        unidades = preparar_unidades(self._snapshot())

        primeira = retropreencher_unidades(self.conn, unidades)
        segunda = retropreencher_unidades(self.conn, unidades)

        self.assertEqual(primeira, 2)
        self.assertEqual(segunda, 0)

    def test_nao_substitui_umb_ja_preenchida(self) -> None:
        self.conn.execute(
            """
            UPDATE fact_mb51_movimentos
            SET unidade_medida_basica = 'UN'
            WHERE documento_material = '500000001';
            """
        )
        unidades = preparar_unidades(self._snapshot())

        retropreencher_unidades(self.conn, unidades)

        unidade = self.conn.execute(
            """
            SELECT unidade_medida_basica
            FROM fact_mb51_movimentos
            WHERE documento_material = '500000001';
            """
        ).fetchone()[0]

        self.assertEqual(unidade, "UN")


if __name__ == "__main__":
    unittest.main()
