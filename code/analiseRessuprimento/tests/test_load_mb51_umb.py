from __future__ import annotations

"""Testes focados no par Quantidade + UMB da carga MB51."""

import sqlite3
import unittest

import pandas as pd

from etl.load_mb51 import carregar_movimentos, preparar_dataframe


class TestLoadMb51Umb(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE fact_mb51_movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT NOT NULL,
                data_lancamento TEXT NOT NULL,
                tipo_movimento TEXT NOT NULL,
                debito_credito TEXT,
                quantidade REAL NOT NULL,
                unidade_medida_basica TEXT,
                documento_material TEXT NOT NULL,
                item_documento TEXT NOT NULL,
                deposito TEXT,
                centro_custo TEXT,
                usuario TEXT,
                arquivo_origem TEXT NOT NULL,
                carregado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (documento_material, item_documento)
            );
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    @staticmethod
    def _linha_excel() -> pd.DataFrame:
        """Simula uma conversão em que a UMB difere da UM de registro."""

        return pd.DataFrame(
            [
                {
                    "Material": 1111111,
                    "Texto breve material": "MATERIAL TESTE",
                    "Data de lançamento": "2026-09-14",
                    "Depósito": "WEPV",
                    "Cód.débito/crédito": "H",
                    "Tipo de movimento": 601,
                    "UM registro": "CX",
                    "Qtd.  UM registro": -1,
                    "Quantidade": -20,
                    "UMB": "PEÇ",
                    "Doc.material": 500000001,
                    "Item doc.material": 1,
                    "Centro custo": None,
                    "Nome do usuário": "TESTE",
                }
            ]
        )

    def test_preparacao_associa_quantidade_a_umb(self) -> None:
        preparado = preparar_dataframe(self._linha_excel())

        self.assertEqual(preparado.loc[0, "quantidade"], -20.0)
        self.assertEqual(
            preparado.loc[0, "unidade_medida_basica"],
            "PEÇ",
        )

    def test_carga_persiste_umb_do_movimento(self) -> None:
        preparado = preparar_dataframe(self._linha_excel())

        inseridas, ignoradas = carregar_movimentos(
            self.conn,
            preparado,
            "MB51_TESTE.xlsx",
        )

        registro = self.conn.execute(
            """
            SELECT quantidade, unidade_medida_basica
            FROM fact_mb51_movimentos;
            """
        ).fetchone()

        self.assertEqual((inseridas, ignoradas), (1, 0))
        self.assertEqual(registro, (-20.0, "PEÇ"))


if __name__ == "__main__":
    unittest.main()
