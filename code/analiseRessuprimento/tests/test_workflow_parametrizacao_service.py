from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from db.schema import criar_schema_plano_parametrizacao
from services.plano_parametrizacao_service import (
    assumir_tarefa,
    criar_plano_parametrizacao,
)


class TestWorkflowParametrizacaoService(unittest.TestCase):

    def setUp(self):
        """
        Usa um banco SQLite físico temporário.

        Diferentemente de ':memory:', o arquivo temporário permite
        abrir duas conexões independentes para testar disputa pela
        mesma tarefa.
        """

        arquivo = tempfile.NamedTemporaryFile(
            suffix=".sqlite",
            delete=False,
        )
        arquivo.close()

        self.db_path = Path(arquivo.name)

        self.conn = sqlite3.connect(
            self.db_path,
            timeout=2.0,
        )
        self.conn.execute(
            "PRAGMA foreign_keys = ON"
        )

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

        self.conn.execute(
            """
            INSERT INTO dim_material (
                material,
                descricao_material
            )
            VALUES (?, ?)
            """,
            (
                "1000001",
                "Material 1",
            ),
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

        if self.db_path.exists():
            self.db_path.unlink()

    def _criar_snapshot(
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
                    "pct_demanda_acumulada": 100.0,
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
            ]
        )

    def _criar_plano(
        self,
        *,
        ativar: bool,
    ) -> tuple[int, int]:
        resultado = criar_plano_parametrizacao(
            self.conn,
            df_snapshot=self._criar_snapshot(),
            nome_plano="Wave Teste",
            onda="TESTE",
            data_inicio_demanda="2026-03-10",
            data_fim_demanda="2026-09-10",
            meses_demanda=6,
            percentual_alvo_demanda=50.0,
            demanda_total_backlog_origem=100.0,
            criado_por="SISTEMA",
        )

        id_plano = resultado["id_plano"]
        id_item = resultado["ids_itens"][0]

        if ativar:
            self.conn.execute(
                """
                UPDATE plano_parametrizacao
                SET status_plano = 'ATIVO'
                WHERE id = ?
                """,
                (id_plano,),
            )
            self.conn.commit()

        return id_plano, id_item

    def test_assume_tarefa_disponivel_de_plano_ativo(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        resultado = assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        self.assertEqual(
            resultado["status_item"],
            "EM_ANALISE",
        )
        self.assertEqual(
            resultado["controlador_responsavel"],
            "CONTROLADOR_1",
        )

        registro = self.conn.execute(
            """
            SELECT
                status_item,
                controlador_responsavel,
                assumido_em
            FROM plano_parametrizacao_item
            WHERE id = ?
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            registro[0],
            "EM_ANALISE",
        )
        self.assertEqual(
            registro[1],
            "CONTROLADOR_1",
        )
        self.assertIsNotNone(
            registro[2]
        )

    def test_registra_historico_ao_assumir_tarefa(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        historico = self.conn.execute(
            """
            SELECT
                tipo_evento,
                status_anterior,
                status_novo,
                usuario,
                origem
            FROM parametrizacao_historico
            WHERE
                id_item_plano = ?
                AND tipo_evento = 'TAREFA_ASSUMIDA'
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            historico,
            (
                "TAREFA_ASSUMIDA",
                "DISPONIVEL",
                "EM_ANALISE",
                "CONTROLADOR_1",
                "USUARIO",
            ),
        )

    def test_rejeita_tarefa_de_plano_rascunho(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=False
        )

        with self.assertRaises(
            ValueError
        ):
            assumir_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
            )

        registro = self.conn.execute(
            """
            SELECT
                status_item,
                controlador_responsavel
            FROM plano_parametrizacao_item
            WHERE id = ?
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            registro,
            (
                "DISPONIVEL",
                None,
            ),
        )

    def test_rejeita_controlador_vazio(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        with self.assertRaises(
            ValueError
        ):
            assumir_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="   ",
            )

    def test_segunda_tentativa_nao_substitui_controlador(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        with self.assertRaises(
            ValueError
        ):
            assumir_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_2",
            )

        registro = self.conn.execute(
            """
            SELECT
                status_item,
                controlador_responsavel
            FROM plano_parametrizacao_item
            WHERE id = ?
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            registro,
            (
                "EM_ANALISE",
                "CONTROLADOR_1",
            ),
        )

    def test_duas_conexoes_nao_assumem_mesma_tarefa(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        conn_2 = sqlite3.connect(
            self.db_path,
            timeout=2.0,
        )
        conn_2.execute(
            "PRAGMA foreign_keys = ON"
        )

        try:
            resultado = assumir_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
            )

            self.assertEqual(
                resultado["controlador_responsavel"],
                "CONTROLADOR_1",
            )

            with self.assertRaises(
                ValueError
            ):
                assumir_tarefa(
                    conn_2,
                    id_item_plano=id_item,
                    controlador="CONTROLADOR_2",
                )

            registro = conn_2.execute(
                """
                SELECT
                    status_item,
                    controlador_responsavel
                FROM plano_parametrizacao_item
                WHERE id = ?
                """,
                (id_item,),
            ).fetchone()

            self.assertEqual(
                registro,
                (
                    "EM_ANALISE",
                    "CONTROLADOR_1",
                ),
            )

        finally:
            conn_2.close()


if __name__ == "__main__":
    unittest.main()
