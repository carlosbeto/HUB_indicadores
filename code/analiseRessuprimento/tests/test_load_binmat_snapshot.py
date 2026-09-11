from __future__ import annotations

import sqlite3
import unittest

import pandas as pd

from etl.load_binmat import carregar_posicoes


class TestLoadBinmatSnapshot(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON;")

        self.conn.execute(
            """
            CREATE TABLE dim_material (
                material TEXT PRIMARY KEY
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE dim_posicao_material (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT NOT NULL,
                deposito TEXT NOT NULL,
                tipo_deposito TEXT NOT NULL,
                posicao TEXT NOT NULL,
                quantidade_minima REAL,
                quantidade_maxima REAL,
                unidade_medida TEXT,
                data_modificacao TEXT,
                momento_criacao TEXT,
                autor TEXT,
                arquivo_origem TEXT,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (material)
                    REFERENCES dim_material(material),

                UNIQUE (
                    deposito,
                    tipo_deposito,
                    posicao,
                    material
                )
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE posicao_material_fontes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_posicao_material INTEGER NOT NULL,
                fonte TEXT NOT NULL,
                primeira_ocorrencia TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultima_ocorrencia TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                arquivo_origem TEXT,
                presente_atual INTEGER NOT NULL DEFAULT 1
                    CHECK (presente_atual IN (0, 1)),

                FOREIGN KEY (id_posicao_material)
                    REFERENCES dim_posicao_material(id)
                    ON DELETE CASCADE,

                UNIQUE (
                    id_posicao_material,
                    fonte
                )
            )
            """
        )

        self.conn.executemany(
            """
            INSERT INTO dim_material (material)
            VALUES (?)
            """,
            [
                ("1111111",),
                ("2222222",),
            ],
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @staticmethod
    def _df_posicoes(
        incluir_material_1=True,
        incluir_material_2=True,
    ):
        registros = []

        if incluir_material_1:
            registros.append(
                {
                    "material": "1111111",
                    "deposito": "1002",
                    "tipo_deposito": "PT02",
                    "posicao": "PT02-001-001-001",
                    "quantidade_minima": 10.0,
                    "quantidade_maxima": 50.0,
                    "unidade_medida": "PC",
                    "data_modificacao": "2026-09-11",
                    "momento_criacao": "2026-01-01 08:00:00",
                    "autor": "TESTE",
                }
            )

        if incluir_material_2:
            registros.append(
                {
                    "material": "2222222",
                    "deposito": "1002",
                    "tipo_deposito": "PT02",
                    "posicao": "PT02-001-002-001",
                    "quantidade_minima": 20.0,
                    "quantidade_maxima": 80.0,
                    "unidade_medida": "PC",
                    "data_modificacao": "2026-09-11",
                    "momento_criacao": "2026-01-01 08:00:00",
                    "autor": "TESTE",
                }
            )

        return pd.DataFrame(registros)

    def _fonte_binmat_por_material(self, material):
        return self.conn.execute(
            """
            SELECT
                f.fonte,
                f.arquivo_origem,
                f.presente_atual,
                f.primeira_ocorrencia,
                f.ultima_ocorrencia
            FROM posicao_material_fontes AS f
            INNER JOIN dim_posicao_material AS p
                ON p.id = f.id_posicao_material
            WHERE
                p.material = ?
                AND f.fonte = 'BINMAT'
            """,
            (material,),
        ).fetchone()

    def test_carga_binmat_marca_posicoes_do_snapshot_como_presentes(self):
        df = self._df_posicoes()

        carregar_posicoes(
            self.conn,
            df,
            "BINMAT_1.xlsx",
        )

        fonte_1 = self._fonte_binmat_por_material(
            "1111111"
        )
        fonte_2 = self._fonte_binmat_por_material(
            "2222222"
        )

        self.assertIsNotNone(fonte_1)
        self.assertIsNotNone(fonte_2)

        self.assertEqual(
            fonte_1[0:3],
            (
                "BINMAT",
                "BINMAT_1.xlsx",
                1,
            ),
        )

        self.assertEqual(
            fonte_2[0:3],
            (
                "BINMAT",
                "BINMAT_1.xlsx",
                1,
            ),
        )

    def test_posicao_ausente_no_novo_snapshot_fica_inativa_no_binmat(
        self,
    ):
        carregar_posicoes(
            self.conn,
            self._df_posicoes(),
            "BINMAT_1.xlsx",
        )

        carregar_posicoes(
            self.conn,
            self._df_posicoes(
                incluir_material_1=True,
                incluir_material_2=False,
            ),
            "BINMAT_2.xlsx",
        )

        fonte_1 = self._fonte_binmat_por_material(
            "1111111"
        )
        fonte_2 = self._fonte_binmat_por_material(
            "2222222"
        )

        self.assertEqual(
            fonte_1[2],
            1,
        )

        self.assertEqual(
            fonte_1[1],
            "BINMAT_2.xlsx",
        )

        self.assertEqual(
            fonte_2[2],
            0,
        )

        posicao_ainda_existe = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM dim_posicao_material
            WHERE material = '2222222'
            """
        ).fetchone()[0]

        self.assertEqual(
            posicao_ainda_existe,
            1,
        )

    def test_posicao_que_reaparece_volta_a_ser_presente(
        self,
    ):
        carregar_posicoes(
            self.conn,
            self._df_posicoes(),
            "BINMAT_1.xlsx",
        )

        fonte_original = self._fonte_binmat_por_material(
            "2222222"
        )

        primeira_ocorrencia_original = (
            fonte_original[3]
        )

        carregar_posicoes(
            self.conn,
            self._df_posicoes(
                incluir_material_1=True,
                incluir_material_2=False,
            ),
            "BINMAT_2.xlsx",
        )

        carregar_posicoes(
            self.conn,
            self._df_posicoes(),
            "BINMAT_3.xlsx",
        )

        fonte_final = self._fonte_binmat_por_material(
            "2222222"
        )

        self.assertEqual(
            fonte_final[2],
            1,
        )

        self.assertEqual(
            fonte_final[1],
            "BINMAT_3.xlsx",
        )

        self.assertEqual(
            fonte_final[3],
            primeira_ocorrencia_original,
        )

    def test_snapshot_binmat_nao_altera_presenca_da_visao_geral(
        self,
    ):
        carregar_posicoes(
            self.conn,
            self._df_posicoes(),
            "BINMAT_1.xlsx",
        )

        id_posicao = self.conn.execute(
            """
            SELECT id
            FROM dim_posicao_material
            WHERE material = '2222222'
            """
        ).fetchone()[0]

        self.conn.execute(
            """
            INSERT INTO posicao_material_fontes (
                id_posicao_material,
                fonte,
                arquivo_origem,
                presente_atual
            )
            VALUES (?, 'VISAO_GERAL', ?, 1)
            """,
            (
                id_posicao,
                "VISAO_1.xlsx",
            ),
        )

        carregar_posicoes(
            self.conn,
            self._df_posicoes(
                incluir_material_1=True,
                incluir_material_2=False,
            ),
            "BINMAT_2.xlsx",
        )

        fontes = self.conn.execute(
            """
            SELECT
                fonte,
                presente_atual
            FROM posicao_material_fontes
            WHERE id_posicao_material = ?
            ORDER BY fonte
            """,
            (id_posicao,),
        ).fetchall()

        self.assertEqual(
            fontes,
            [
                ("BINMAT", 0),
                ("VISAO_GERAL", 1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
