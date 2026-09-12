from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

CREATE_DATABASE_PATH = (
    BASE_DIR
    / "etl"
    / "create_database.py"
)


def carregar_create_database():
    """
    Carrega create_database.py diretamente pelo caminho.

    Evita depender da forma como o projeto foi iniciado
    pelo terminal ou pelo VS Code.
    """

    spec = importlib.util.spec_from_file_location(
        "create_database_ressuprimento",
        CREATE_DATABASE_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Não foi possível carregar create_database.py."
        )

    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    return modulo


class TestCreateDatabase(unittest.TestCase):

    def setUp(self) -> None:
        """
        Para cada teste é criado um banco SQLite descartável.

        Nenhum teste utiliza o banco DEV real.
        """

        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "ressuprimento_teste.sqlite"
        )

        modulo = carregar_create_database()

        modulo.criar_banco(self.db_path)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def tearDown(self) -> None:
        """
        Encerra explicitamente qualquer transação pendente antes
        de fechar a conexão.

        Isso é especialmente importante no Windows, onde um
        arquivo SQLite ainda aberto não pode ser removido pela
        pasta temporária.
        """

        try:
            self.conn.rollback()
        finally:
            self.conn.close()

        self.temp_dir.cleanup()

    def test_schema_completo_e_migration_registrada(self) -> None:
        """
        Valida que um banco novo nasce com:

        - schema operacional;
        - schema do plano de parametrização;
        - migration 001 registrada.
        """

        tabelas_esperadas = {
            "dim_material",
            "fact_mb51_movimentos",
            "dim_posicao_material",
            "fact_saldo_posicao",
            "posicao_material_fontes",
            "etl_execucoes",
            "etl_arquivos_processados",
            "schema_migrations",
            "plano_parametrizacao",
            "plano_parametrizacao_item",
            "parametrizacao_decisao",
            "parametrizacao_confirmacao",
            "parametrizacao_historico",
        }

        tabelas_encontradas = {
            row[0]
            for row in self.conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table';
                """
            ).fetchall()
        }

        self.assertTrue(
            tabelas_esperadas.issubset(tabelas_encontradas)
        )

        migration = self.conn.execute(
            """
            SELECT
                version,
                nome
            FROM schema_migrations
            WHERE version = 1;
            """
        ).fetchone()

        self.assertEqual(
            migration,
            (
                1,
                "001_cria_plano_parametrizacao",
            ),
        )

    def test_foreign_keys_integras(self) -> None:
        """
        Valida a integridade referencial do banco recém-criado.
        """

        erros = self.conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        self.assertEqual(erros, [])

    def test_status_plano_invalido_e_rejeitado(self) -> None:
        """
        Valida CHECK de status do plano.
        """

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO plano_parametrizacao (
                    nome_plano,
                    data_inicio_demanda,
                    data_fim_demanda,
                    meses_demanda,
                    criterio_prioridade,
                    quantidade_materiais,
                    demanda_total_plano,
                    demanda_total_backlog_origem,
                    percentual_real_cobertura,
                    status_plano,
                    criado_por
                )
                VALUES (
                    'PLANO TESTE',
                    '2026-03-10',
                    '2026-09-10',
                    6,
                    'DEMANDA_RELEVANTE_6M',
                    1,
                    100,
                    100,
                    100,
                    'STATUS_INVALIDO',
                    'TESTE'
                );
                """
            )

    def test_parametrizar_exige_min_max_validos(self) -> None:
        """
        Valida que uma decisão PARAMETRIZAR não pode ser
        registrada sem MIN/MAX coerentes.
        """

        id_item = self._criar_item_valido()

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO parametrizacao_decisao (
                    id_item_plano,
                    numero_revisao,
                    decisao,
                    controlador
                )
                VALUES (?, 1, 'PARAMETRIZAR', 'TESTE');
                """,
                (id_item,),
            )

    def test_apenas_uma_decisao_ativa_por_item(self) -> None:
        """
        Valida o índice único parcial que permite somente
        uma decisão vigente por item.
        """

        id_item = self._criar_item_valido()

        self.conn.execute(
            """
            INSERT INTO usuarios (
                matricula,
                nome
            )
            VALUES (
                'TT000001',
                'USUARIO TESTE'
            );
            """
        )

        self.conn.execute(
            """
            INSERT INTO parametrizacao_decisao (
                id_item_plano,
                numero_revisao,
                decisao,
                controlador,
                ativo
            )
            VALUES (
                ?,
                1,
                'INVESTIGAR',
                'TT000001',
                1
            );
            """,
            (id_item,),
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO parametrizacao_decisao (
                    id_item_plano,
                    numero_revisao,
                    decisao,
                    controlador,
                    ativo
                )
                VALUES (
                    ?,
                    2,
                    'REVISAR_POSTERIORMENTE',
                    'TT000001',
                    1
                );
                """,
                (id_item,),
            )

    def _criar_item_valido(self) -> int:
        """
        Cria a estrutura mínima válida necessária aos testes
        de decisão.
        """

        self.conn.execute(
            """
            INSERT INTO dim_material (
                material,
                descricao_material
            )
            VALUES (
                '9999999',
                'MATERIAL TESTE'
            );
            """
        )

        cursor = self.conn.execute(
            """
            INSERT INTO plano_parametrizacao (
                nome_plano,
                onda,
                data_inicio_demanda,
                data_fim_demanda,
                meses_demanda,
                criterio_prioridade,
                percentual_alvo_demanda,
                quantidade_materiais,
                demanda_total_plano,
                demanda_total_backlog_origem,
                percentual_real_cobertura,
                status_plano,
                criado_por
            )
            VALUES (
                'PLANO TESTE',
                'TESTE',
                '2026-03-10',
                '2026-09-10',
                6,
                'DEMANDA_RELEVANTE_6M',
                50,
                1,
                100,
                200,
                50,
                'RASCUNHO',
                'TESTE'
            );
            """
        )

        id_plano = cursor.lastrowid

        cursor = self.conn.execute(
            """
            INSERT INTO plano_parametrizacao_item (
                id_plano,
                material,
                posicao_pt02,
                prioridade_inicial,
                demanda_relevante_inicial,
                status_item
            )
            VALUES (
                ?,
                '9999999',
                'PT02-TESTE-001',
                1,
                100,
                'DISPONIVEL'
            );
            """,
            (id_plano,),
        )

        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
