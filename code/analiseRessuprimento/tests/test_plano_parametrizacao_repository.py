from __future__ import annotations

import sqlite3
import unittest

from db.schema import criar_schema_plano_parametrizacao
from repositories.plano_parametrizacao_repository import (
    contar_historicos_plano,
    contar_itens_plano,
    inserir_historico_parametrizacao,
    inserir_item_plano_parametrizacao,
    inserir_plano_parametrizacao,
    listar_fila_operacional_plano,
    listar_itens_plano,
    obter_plano_por_id,
    obter_resumo_operacional_plano,
)


class TestPlanoParametrizacaoRepository(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Tabelas-base mínimas necessárias para as FKs
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

        criar_schema_plano_parametrizacao(self.conn)

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
                "Material de teste",
            ),
        )

    def tearDown(self):
        self.conn.close()

    def _criar_plano(self) -> int:
        return inserir_plano_parametrizacao(
            self.conn,
            nome_plano="Wave A",
            onda="A",
            data_inicio_demanda="2026-03-10",
            data_fim_demanda="2026-09-10",
            meses_demanda=6,
            criterio_prioridade="DEMANDA_RELEVANTE_DESC",
            percentual_alvo_demanda=50.0,
            quantidade_materiais=37,
            demanda_total_plano=86497.0,
            demanda_total_backlog_origem=172148.0,
            percentual_real_cobertura=50.24571880010223,
            status_plano="RASCUNHO",
            criado_por="TESTE",
            observacao="Plano criado em teste automatizado.",
        )

    def _criar_item(self, id_plano: int) -> int:
        return inserir_item_plano_parametrizacao(
            self.conn,
            id_plano=id_plano,
            material="1000001",
            posicao_pt02="PT02-001-001-001",
            descricao_material="Material de teste",
            prioridade_inicial=1,
            demanda_comercial_inicial=90.0,
            demanda_tecnica_inicial=10.0,
            demanda_relevante_inicial=100.0,
            pct_demanda_acumulada_inicial=15.0,
            min_inicial=0.0,
            max_inicial=0.0,
            saldo_pt02_f5_inicial=25.0,
            saldo_pt02_b5_inicial=0.0,
            saldo_t001_f5_inicial=50.0,
            saldo_t001_b5_inicial=0.0,
            qtd_posicoes_t001_inicial=2,
            situacao_fisica_inicial=(
                "PT02 COM F5 + T001 COM F5"
            ),
            status_item="DISPONIVEL",
        )

    def test_insere_e_recupera_plano(self):
        id_plano = self._criar_plano()

        plano = obter_plano_por_id(
            self.conn,
            id_plano,
        )

        self.assertIsNotNone(plano)
        self.assertEqual(
            plano[1],
            "Wave A",
        )

    def test_insere_item_e_conta_itens(self):
        id_plano = self._criar_plano()

        id_item = self._criar_item(
            id_plano
        )

        self.assertGreater(
            id_item,
            0,
        )

        self.assertEqual(
            contar_itens_plano(
                self.conn,
                id_plano,
            ),
            1,
        )

    def test_insere_historico_e_conta_eventos(self):
        id_plano = self._criar_plano()

        id_item = self._criar_item(
            id_plano
        )

        id_historico = inserir_historico_parametrizacao(
            self.conn,
            id_item_plano=id_item,
            tipo_evento="ITEM_CRIADO",
            usuario="TESTE",
            origem="SISTEMA",
            descricao="Item criado no plano.",
            status_anterior=None,
            status_novo="DISPONIVEL",
        )

        self.assertGreater(
            id_historico,
            0,
        )

        self.assertEqual(
            contar_historicos_plano(
                self.conn,
                id_plano,
            ),
            1,
        )

    def test_lista_itens_por_prioridade(self):
        id_plano = self._criar_plano()

        self._criar_item(
            id_plano
        )

        itens = listar_itens_plano(
            self.conn,
            id_plano,
        )

        self.assertEqual(
            len(itens),
            1,
        )

        # prioridade_inicial
        self.assertEqual(
            itens[0][5],
            1,
        )

    def test_lista_fila_operacional_com_contrato_explicito(self):
        id_plano = self._criar_plano()

        id_item = self._criar_item(
            id_plano
        )

        fila = listar_fila_operacional_plano(
            self.conn,
            id_plano=id_plano,
        )

        self.assertEqual(
            len(fila),
            1,
        )

        item = fila[0]

        self.assertEqual(
            item["id_item_plano"],
            id_item,
        )
        self.assertEqual(
            item["material"],
            "1000001",
        )
        self.assertEqual(
            item["descricao_material"],
            "Material de teste",
        )
        self.assertEqual(
            item["posicao_pt02"],
            "PT02-001-001-001",
        )
        self.assertEqual(
            item["prioridade"],
            1,
        )
        self.assertEqual(
            item["demanda_relevante"],
            100.0,
        )
        self.assertEqual(
            item["pct_demanda_acumulada"],
            15.0,
        )
        self.assertEqual(
            item["status"],
            "DISPONIVEL",
        )
        self.assertIsNone(
            item["controlador_responsavel"],
        )
        self.assertIsNone(
            item["assumido_em"],
        )

    def test_fk_impede_material_inexistente(self):
        id_plano = self._criar_plano()

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            inserir_item_plano_parametrizacao(
                self.conn,
                id_plano=id_plano,
                material="9999999",
                posicao_pt02="PT02-999-999-999",
                descricao_material="Inexistente",
                prioridade_inicial=1,
                demanda_comercial_inicial=10.0,
                demanda_tecnica_inicial=0.0,
                demanda_relevante_inicial=10.0,
                pct_demanda_acumulada_inicial=100.0,
                min_inicial=0.0,
                max_inicial=0.0,
                saldo_pt02_f5_inicial=None,
                saldo_pt02_b5_inicial=None,
                saldo_t001_f5_inicial=0.0,
                saldo_t001_b5_inicial=0.0,
                qtd_posicoes_t001_inicial=0,
                situacao_fisica_inicial=(
                    "PT02 NÃO IDENTIFICADO + "
                    "SEM T001 F5"
                ),
                status_item="DISPONIVEL",
            )

    def test_obtem_resumo_operacional_plano_com_contrato_explicito(self):
        id_plano = self._criar_plano()

        resumo = obter_resumo_operacional_plano(
            self.conn,
            id_plano=id_plano,
        )

        self.assertIsNotNone(
            resumo,
        )

        self.assertEqual(
            resumo["id_plano"],
            id_plano,
        )
        self.assertEqual(
            resumo["nome"],
            "Wave A",
        )
        self.assertEqual(
            resumo["onda"],
            "A",
        )
        self.assertEqual(
            resumo["status"],
            "RASCUNHO",
        )

if __name__ == "__main__":
    unittest.main()
