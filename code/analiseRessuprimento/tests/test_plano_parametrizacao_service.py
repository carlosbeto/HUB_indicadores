from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

from db.schema import criar_schema_plano_parametrizacao
from services.plano_parametrizacao_service import (
    criar_plano_parametrizacao,
)


class TestPlanoParametrizacaoService(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Estrutura-base mínima necessária para as FKs
        self.conn.execute(
            """
            CREATE TABLE dim_material (
                material TEXT PRIMARY KEY,
                descricao_material TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        criar_schema_plano_parametrizacao(
            self.conn
        )

        self.conn.executemany(
            """
            INSERT INTO dim_material (
                material,
                descricao_material
            )
            VALUES (?, ?)
            """,
            [
                (
                    "1000001",
                    "Material 1",
                ),
                (
                    "1000002",
                    "Material 2",
                ),
            ],
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _criar_snapshot_valido(
        self,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                    "descricao_material": "Material 1",
                    "demanda_comercial": 90.0,
                    "demanda_tecnica": 10.0,
                    "demanda_relevante": 100.0,
                    "pct_demanda_acumulada": 62.5,
                    "quantidade_minima": 0.0,
                    "quantidade_maxima": 0.0,
                    "saldo_pt02_f5": 25.0,
                    "saldo_pt02_b5": 0.0,
                    "saldo_t001_f5": 50.0,
                    "saldo_t001_b5": 0.0,
                    "qtd_posicoes_t001": 2,
                    "situacao_fisica": (
                        "PT02 COM F5 + T001 COM F5"
                    ),
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "posicao": "PT02-001-001-002",
                    "descricao_material": "Material 2",
                    "demanda_comercial": 60.0,
                    "demanda_tecnica": 0.0,
                    "demanda_relevante": 60.0,
                    "pct_demanda_acumulada": 100.0,
                    "quantidade_minima": 0.0,
                    "quantidade_maxima": 0.0,
                    "saldo_pt02_f5": None,
                    "saldo_pt02_b5": None,
                    "saldo_t001_f5": 0.0,
                    "saldo_t001_b5": 0.0,
                    "qtd_posicoes_t001": 0,
                    "situacao_fisica": (
                        "PT02 NÃO IDENTIFICADO + "
                        "SEM T001 F5"
                    ),
                },
            ]
        )

    def _criar_plano(
        self,
        df_snapshot: pd.DataFrame,
    ) -> dict:
        return criar_plano_parametrizacao(
            self.conn,
            df_snapshot=df_snapshot,
            nome_plano="Wave A",
            onda="A",
            data_inicio_demanda="2026-03-10",
            data_fim_demanda="2026-09-10",
            meses_demanda=6,
            percentual_alvo_demanda=50.0,
            demanda_total_backlog_origem=160.0,
            criado_por="SISTEMA",
            observacao=(
                "Plano criado pelo teste automatizado."
            ),
        )

    def test_cria_plano_itens_e_historicos(
        self,
    ):
        df_snapshot = (
            self._criar_snapshot_valido()
        )

        resultado = self._criar_plano(
            df_snapshot
        )

        self.assertEqual(
            resultado["status_plano"],
            "RASCUNHO",
        )

        self.assertEqual(
            resultado["quantidade_materiais"],
            2,
        )

        self.assertEqual(
            resultado["demanda_total_plano"],
            160.0,
        )

        self.assertEqual(
            resultado[
                "percentual_real_cobertura"
            ],
            100.0,
        )

        qtd_planos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM plano_parametrizacao
            """
        ).fetchone()[0]

        qtd_itens = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM plano_parametrizacao_item
            """
        ).fetchone()[0]

        qtd_historicos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM parametrizacao_historico
            """
        ).fetchone()[0]

        self.assertEqual(
            qtd_planos,
            1,
        )

        self.assertEqual(
            qtd_itens,
            2,
        )

        self.assertEqual(
            qtd_historicos,
            2,
        )

    def test_preserva_null_quando_pt02_nao_identificada(
        self,
    ):
        df_snapshot = (
            self._criar_snapshot_valido()
        )

        resultado = self._criar_plano(
            df_snapshot
        )

        id_plano = resultado[
            "id_plano"
        ]

        registro = self.conn.execute(
            """
            SELECT
                saldo_pt02_f5_inicial,
                saldo_pt02_b5_inicial
            FROM plano_parametrizacao_item
            WHERE
                id_plano = ?
                AND material = ?
            """,
            (
                id_plano,
                "1000002",
            ),
        ).fetchone()

        self.assertIsNone(
            registro[0]
        )

        self.assertIsNone(
            registro[1]
        )

    def test_status_inicial_dos_itens_e_disponivel(
        self,
    ):
        df_snapshot = (
            self._criar_snapshot_valido()
        )

        resultado = self._criar_plano(
            df_snapshot
        )

        id_plano = resultado[
            "id_plano"
        ]

        status = self.conn.execute(
            """
            SELECT DISTINCT status_item
            FROM plano_parametrizacao_item
            WHERE id_plano = ?
            """,
            (
                id_plano,
            ),
        ).fetchall()

        self.assertEqual(
            status,
            [
                ("DISPONIVEL",),
            ],
        )

    def test_rejeita_snapshot_com_demanda_nao_positiva(
        self,
    ):
        df_snapshot = (
            self._criar_snapshot_valido()
        )

        df_snapshot.loc[
            0,
            "demanda_relevante",
        ] = 0.0

        with self.assertRaises(
            ValueError
        ):
            self._criar_plano(
                df_snapshot
            )

        qtd_planos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM plano_parametrizacao
            """
        ).fetchone()[0]

        self.assertEqual(
            qtd_planos,
            0,
        )

    @patch(
        "services.plano_parametrizacao_service."
        "inserir_historico_parametrizacao"
    )
    def test_rollback_remove_tudo_se_historico_falhar(
        self,
        mock_historico,
    ):
        """
        Simula erro durante a criação do histórico.

        O plano e seus itens já terão começado a ser
        inseridos, portanto o rollback precisa desfazer
        toda a operação.
        """

        mock_historico.side_effect = RuntimeError(
            "Falha simulada no histórico."
        )

        df_snapshot = (
            self._criar_snapshot_valido()
        )

        with self.assertRaises(
            RuntimeError
        ):
            self._criar_plano(
                df_snapshot
            )

        qtd_planos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM plano_parametrizacao
            """
        ).fetchone()[0]

        qtd_itens = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM plano_parametrizacao_item
            """
        ).fetchone()[0]

        qtd_historicos = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM parametrizacao_historico
            """
        ).fetchone()[0]

        self.assertEqual(
            qtd_planos,
            0,
        )

        self.assertEqual(
            qtd_itens,
            0,
        )

        self.assertEqual(
            qtd_historicos,
            0,
        )


if __name__ == "__main__":
    unittest.main()
