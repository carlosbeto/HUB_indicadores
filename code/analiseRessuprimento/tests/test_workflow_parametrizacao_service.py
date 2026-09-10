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
    liberar_tarefa,
    registrar_decisao,
    revisar_decisao,
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

    def test_libera_tarefa_assumida_pelo_mesmo_controlador(
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

        resultado = liberar_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        self.assertEqual(
            resultado["status_item"],
            "DISPONIVEL",
        )

        self.assertIsNone(
            resultado["controlador_responsavel"]
        )

        self.assertIsNone(
            resultado["assumido_em"]
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
            registro,
            (
                "DISPONIVEL",
                None,
                None,
            ),
        )

    def test_registra_historico_ao_liberar_tarefa(
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

        liberar_tarefa(
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
                AND tipo_evento = 'TAREFA_LIBERADA'
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            historico,
            (
                "TAREFA_LIBERADA",
                "EM_ANALISE",
                "DISPONIVEL",
                "CONTROLADOR_1",
                "USUARIO",
            ),
        )

    def test_rejeita_liberacao_por_outro_controlador(
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
            liberar_tarefa(
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

    def test_rejeita_liberacao_de_tarefa_disponivel(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        with self.assertRaises(
            ValueError
        ):
            liberar_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
            )

    def test_rejeita_liberacao_com_controlador_vazio(
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
            liberar_tarefa(
                self.conn,
                id_item_plano=id_item,
                controlador="   ",
            )

    def test_libera_sem_alterar_prioridade_inicial(
        self,
    ):
        _, id_item = self._criar_plano(
            ativar=True
        )

        prioridade_antes = self.conn.execute(
            """
            SELECT prioridade_inicial
            FROM plano_parametrizacao_item
            WHERE id = ?
            """,
            (id_item,),
        ).fetchone()[0]

        assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        liberar_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        prioridade_depois = self.conn.execute(
            """
            SELECT prioridade_inicial
            FROM plano_parametrizacao_item
            WHERE id = ?
            """,
            (id_item,),
        ).fetchone()[0]

        self.assertEqual(
            prioridade_depois,
            prioridade_antes,
        )


    def test_parametrizar_avanca_para_aguardando_confirmacao_sap(
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

        resultado = registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="PARAMETRIZAR",
            min_proposto=10.0,
            max_proposto=50.0,
        )

        self.assertEqual(
            resultado["status_item"],
            "AGUARDANDO_CONFIRMACAO_SAP",
        )

        decisao = self.conn.execute(
            """
            SELECT
                numero_revisao,
                decisao,
                min_proposto,
                max_proposto,
                controlador,
                ativo
            FROM parametrizacao_decisao
            WHERE id_item_plano = ?
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            decisao,
            (
                1,
                "PARAMETRIZAR",
                10.0,
                50.0,
                "CONTROLADOR_1",
                1,
            ),
        )

    def test_rejeita_parametrizar_sem_minimo(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                max_proposto=50.0,
            )

    def test_rejeita_parametrizar_sem_maximo(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                min_proposto=10.0,
            )

    def test_rejeita_parametrizar_com_minimo_negativo(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                min_proposto=-1.0,
                max_proposto=50.0,
            )

    def test_rejeita_parametrizar_com_maximo_menor_que_minimo(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                min_proposto=50.0,
                max_proposto=10.0,
            )

    def test_nao_parametrizar_encerra_item(
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

        resultado = registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="NAO_PARAMETRIZAR",
            justificativa="Material não deve ser parametrizado.",
        )

        self.assertEqual(
            resultado["status_item"],
            "ENCERRADO_SEM_PARAMETRIZACAO",
        )

    def test_investigar_mantem_item_em_analise(
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

        resultado = registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Necessário validar situação física.",
        )

        self.assertEqual(
            resultado["status_item"],
            "EM_ANALISE",
        )
        self.assertEqual(
            resultado["controlador_responsavel"],
            "CONTROLADOR_1",
        )

    def test_revisar_posteriormente_mantem_item_em_analise(
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

        resultado = registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="REVISAR_POSTERIORMENTE",
            justificativa="Reavaliar após nova informação.",
        )

        self.assertEqual(
            resultado["status_item"],
            "EM_ANALISE",
        )
        self.assertEqual(
            resultado["controlador_responsavel"],
            "CONTROLADOR_1",
        )

    def test_rejeita_decisoes_nao_parametrizadoras_sem_justificativa(
        self,
    ):
        for decisao in (
            "NAO_PARAMETRIZAR",
            "INVESTIGAR",
            "REVISAR_POSTERIORMENTE",
        ):
            with self.subTest(decisao=decisao):
                _, id_item = self._criar_plano(
                    ativar=True
                )

                assumir_tarefa(
                    self.conn,
                    id_item_plano=id_item,
                    controlador="CONTROLADOR_1",
                )

                with self.assertRaises(ValueError):
                    registrar_decisao(
                        self.conn,
                        id_item_plano=id_item,
                        controlador="CONTROLADOR_1",
                        decisao=decisao,
                        justificativa="   ",
                    )

    def test_rejeita_min_max_em_decisao_nao_parametrizadora(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="INVESTIGAR",
                justificativa="Necessário investigar.",
                min_proposto=10.0,
                max_proposto=50.0,
            )

    def test_rejeita_decisao_por_outro_controlador(
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

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_2",
                decisao="INVESTIGAR",
                justificativa="Teste.",
            )

    def test_rejeita_decisao_em_plano_nao_ativo(
        self,
    ):
        id_plano, id_item = self._criar_plano(
            ativar=True
        )

        assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        self.conn.execute(
            """
            UPDATE plano_parametrizacao
            SET status_plano = 'RASCUNHO'
            WHERE id = ?
            """,
            (id_plano,),
        )
        self.conn.commit()

        with self.assertRaises(ValueError):
            registrar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="INVESTIGAR",
                justificativa="Teste.",
            )

    def test_registra_historico_da_decisao(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="PARAMETRIZAR",
            min_proposto=10.0,
            max_proposto=50.0,
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
                AND tipo_evento = 'DECISAO_REGISTRADA'
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            historico,
            (
                "DECISAO_REGISTRADA",
                "EM_ANALISE",
                "AGUARDANDO_CONFIRMACAO_SAP",
                "CONTROLADOR_1",
                "USUARIO",
            ),
        )


    def test_revisa_decisao_investigar_para_parametrizar(
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

        primeira = registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Validar situação física.",
        )

        segunda = revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="PARAMETRIZAR",
            min_proposto=10.0,
            max_proposto=50.0,
        )

        self.assertEqual(
            primeira["numero_revisao"],
            1,
        )
        self.assertEqual(
            segunda["numero_revisao"],
            2,
        )
        self.assertEqual(
            segunda["status_item"],
            "AGUARDANDO_CONFIRMACAO_SAP",
        )
        self.assertEqual(
            segunda["controlador_responsavel"],
            "CONTROLADOR_1",
        )

    def test_revisao_inativa_decisao_anterior(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="REVISAR_POSTERIORMENTE",
            justificativa="Aguardar nova informação.",
        )

        decisoes = self.conn.execute(
            """
            SELECT
                numero_revisao,
                decisao,
                ativo
            FROM parametrizacao_decisao
            WHERE id_item_plano = ?
            ORDER BY numero_revisao
            """,
            (id_item,),
        ).fetchall()

        self.assertEqual(
            decisoes,
            [
                (
                    1,
                    "INVESTIGAR",
                    0,
                ),
                (
                    2,
                    "REVISAR_POSTERIORMENTE",
                    1,
                ),
            ],
        )

    def test_revisao_mantem_apenas_uma_decisao_ativa(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="REVISAR_POSTERIORMENTE",
            justificativa="Segunda análise.",
        )

        quantidade_ativas = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM parametrizacao_decisao
            WHERE
                id_item_plano = ?
                AND ativo = 1
            """,
            (id_item,),
        ).fetchone()[0]

        self.assertEqual(
            quantidade_ativas,
            1,
        )

    def test_revisao_incrementa_numero_revisao(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        segunda = revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="REVISAR_POSTERIORMENTE",
            justificativa="Segunda análise.",
        )

        terceira = revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Terceira análise.",
        )

        self.assertEqual(
            segunda["numero_revisao"],
            2,
        )
        self.assertEqual(
            terceira["numero_revisao"],
            3,
        )

    def test_revisao_preserva_historico_das_decisoes(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="REVISAR_POSTERIORMENTE",
            justificativa="Segunda análise.",
        )

        revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Terceira análise.",
        )

        quantidade = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM parametrizacao_decisao
            WHERE id_item_plano = ?
            """,
            (id_item,),
        ).fetchone()[0]

        self.assertEqual(
            quantidade,
            3,
        )

    def test_registra_historico_ao_revisar_decisao(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        revisar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="PARAMETRIZAR",
            min_proposto=10.0,
            max_proposto=50.0,
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
                AND tipo_evento = 'DECISAO_REVISADA'
            """,
            (id_item,),
        ).fetchone()

        self.assertEqual(
            historico,
            (
                "DECISAO_REVISADA",
                "EM_ANALISE",
                "AGUARDANDO_CONFIRMACAO_SAP",
                "CONTROLADOR_1",
                "USUARIO",
            ),
        )

    def test_rejeita_revisao_por_outro_controlador(
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

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        with self.assertRaises(ValueError):
            revisar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_2",
                decisao="PARAMETRIZAR",
                min_proposto=10.0,
                max_proposto=50.0,
            )

    def test_rejeita_revisao_sem_decisao_ativa_anterior(
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

        with self.assertRaises(ValueError):
            revisar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                min_proposto=10.0,
                max_proposto=50.0,
            )

    def test_rejeita_revisao_em_plano_nao_ativo(
        self,
    ):
        id_plano, id_item = self._criar_plano(
            ativar=True
        )

        assumir_tarefa(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
        )

        registrar_decisao(
            self.conn,
            id_item_plano=id_item,
            controlador="CONTROLADOR_1",
            decisao="INVESTIGAR",
            justificativa="Primeira análise.",
        )

        self.conn.execute(
            """
            UPDATE plano_parametrizacao
            SET status_plano = 'RASCUNHO'
            WHERE id = ?
            """,
            (id_plano,),
        )
        self.conn.commit()

        with self.assertRaises(ValueError):
            revisar_decisao(
                self.conn,
                id_item_plano=id_item,
                controlador="CONTROLADOR_1",
                decisao="PARAMETRIZAR",
                min_proposto=10.0,
                max_proposto=50.0,
            )

if __name__ == "__main__":
    unittest.main()
