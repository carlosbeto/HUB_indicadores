from __future__ import annotations

"""Testes do contrato de UMB retornado pela demanda MB51."""

import sqlite3
import unittest

from repositories.demanda_repository import carregar_demanda_material


class TestDemandaUmbRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE fact_mb51_movimentos (
                material TEXT NOT NULL,
                data_lancamento TEXT NOT NULL,
                tipo_movimento TEXT NOT NULL,
                debito_credito TEXT,
                quantidade REAL NOT NULL,
                unidade_medida_basica TEXT
            );
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def _inserir(self, material: str, umb: str | None) -> None:
        self.conn.execute(
            """
            INSERT INTO fact_mb51_movimentos (
                material,
                data_lancamento,
                tipo_movimento,
                debito_credito,
                quantidade,
                unidade_medida_basica
            )
            VALUES (?, '2026-09-14', '601', 'H', -10, ?);
            """,
            (material, umb),
        )

    def test_retorna_umb_consistente_do_material(self) -> None:
        self._inserir("1000001", "PEÇ")
        self._inserir("1000001", "PEÇ")

        demanda, _, _ = carregar_demanda_material(self.conn)
        item = demanda.iloc[0]

        self.assertEqual(item["unidade_medida_basica"], "PEÇ")
        self.assertEqual(item["quantidade_umb_distintas"], 1)
        self.assertEqual(item["status_umb"], "UMB CONSISTENTE")

    def test_sinaliza_umb_ausente(self) -> None:
        self._inserir("1000001", None)

        demanda, _, _ = carregar_demanda_material(self.conn)
        item = demanda.iloc[0]

        self.assertTrue(item.isna()["unidade_medida_basica"])
        self.assertEqual(item["quantidade_umb_distintas"], 0)
        self.assertEqual(item["status_umb"], "UMB NÃO INFORMADA")

    def test_nao_escolhe_unidade_quando_existe_conflito(self) -> None:
        self._inserir("1000001", "PEÇ")
        self._inserir("1000001", "CX")

        demanda, _, _ = carregar_demanda_material(self.conn)
        item = demanda.iloc[0]

        self.assertTrue(item.isna()["unidade_medida_basica"])
        self.assertEqual(item["quantidade_umb_distintas"], 2)
        self.assertEqual(item["status_umb"], "UMB CONFLITANTE")


if __name__ == "__main__":
    unittest.main()
