from __future__ import annotations

"""
Testes da migration 002 sem acesso ao banco DEV real.

Cada cenário cria um SQLite descartável. Parte dos testes valida que um
banco novo recebe automaticamente as migrations 001 e 002. Os demais
simulam um banco legado parado na versão 001, adicionam dados anteriores
e só então executam a 002 para comprovar preservação e integridade.
"""

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


BASE_DIR = Path(__file__).resolve().parent.parent

CREATE_DATABASE_PATH = (
    BASE_DIR
    / "etl"
    / "create_database.py"
)

MIGRATION_002_PATH = (
    BASE_DIR
    / "migrations"
    / "002_cria_usuarios_e_relacionamentos.py"
)


def carregar_modulo(caminho: Path, nome_modulo: str):
    """Importa scripts numerados diretamente pelo caminho do arquivo."""

    spec = importlib.util.spec_from_file_location(
        nome_modulo,
        caminho,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Não foi possível carregar {caminho.name}."
        )

    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    return modulo


class TestArquivoMigration002(unittest.TestCase):
    """Valida existência e integração da migration no criador do banco."""

    def test_migration_002_existe(self) -> None:
        """Impede que os contratos sejam ignorados sem a migration."""

        self.assertTrue(
            MIGRATION_002_PATH.exists(),
            "A migration 002 ainda não foi criada.",
        )

    def test_create_database_aplica_migration_002(self) -> None:
        """Confirma que um banco novo já nasce na versão estrutural 002."""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = (
                Path(temp_dir)
                / "ressuprimento_novo.sqlite"
            )

            create_database = carregar_modulo(
                CREATE_DATABASE_PATH,
                "create_database_com_migration_002",
            )
            create_database.criar_banco(db_path)

            conn = sqlite3.connect(db_path)

            try:
                migration = conn.execute(
                    """
                    SELECT version, nome
                    FROM schema_migrations
                    WHERE version = 2;
                    """
                ).fetchone()

                self.assertEqual(
                    migration,
                    (
                        2,
                        "002_cria_usuarios_e_relacionamentos",
                    ),
                )

                tabela = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'usuarios';
                    """
                ).fetchone()

                self.assertEqual(tabela, ("usuarios",))

            finally:
                conn.close()


@unittest.skipUnless(
    MIGRATION_002_PATH.exists(),
    "A migration 002 ainda não foi criada.",
)
class TestMigration002Usuarios(unittest.TestCase):
    """Exercita a atualização de um banco legado da versão 001 para 002."""

    def setUp(self) -> None:
        """Cria um banco temporário na versão 001 e aplica a migration 002."""

        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "ressuprimento_teste.sqlite"
        )

        create_database = carregar_modulo(
            CREATE_DATABASE_PATH,
            "create_database_antes_migration_002",
        )

        # O criador oficial já conhece a migration 002. Aqui ela é
        # neutralizada para reproduzir o banco DEV antes da atualização:
        # schema-base e migration 001, mas ainda sem a migration 002.
        create_database.carregar_migration_002 = lambda: (
            SimpleNamespace(
                aplicar_migration=lambda _db_path: None,
            )
        )

        # A migration 003 depende formalmente da 002. Como este teste
        # precisa observar o banco exatamente antes da versão 002, também
        # neutralizamos as migrations posteriores durante a preparação.
        create_database.carregar_migration_003 = lambda: (
            SimpleNamespace(
                aplicar_migration=lambda _db_path: None,
            )
        )

        create_database.criar_banco(self.db_path)

        self._criar_baseline_anterior()

        migration_002 = carregar_modulo(
            MIGRATION_002_PATH,
            "migration_002_usuarios",
        )
        migration_002.aplicar_migration(self.db_path)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def tearDown(self) -> None:
        """Fecha conexões antes de remover o SQLite temporário no Windows."""

        if hasattr(self, "conn"):
            try:
                self.conn.rollback()
            finally:
                self.conn.close()

        self.temp_dir.cleanup()

    def _criar_baseline_anterior(self) -> None:
        """Insere plano, item e histórico anteriores à versão 002."""

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")

        try:
            conn.execute(
                """
                INSERT INTO dim_material (
                    material,
                    descricao_material
                )
                VALUES ('1000001', 'MATERIAL TESTE');
                """
            )

            cursor = conn.execute(
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
                    'WAVE A',
                    '2026-03-10',
                    '2026-09-10',
                    6,
                    'DEMANDA_RELEVANTE_DESC',
                    50,
                    1,
                    10,
                    20,
                    50,
                    'RASCUNHO',
                    'SISTEMA'
                );
                """
            )
            id_plano = int(cursor.lastrowid)

            cursor = conn.execute(
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
                    '1000001',
                    'PT02-TESTE',
                    1,
                    10,
                    'DISPONIVEL'
                );
                """,
                (id_plano,),
            )
            id_item = int(cursor.lastrowid)

            conn.execute(
                """
                INSERT INTO parametrizacao_historico (
                    id_item_plano,
                    tipo_evento,
                    status_novo,
                    usuario,
                    origem,
                    descricao
                )
                VALUES (
                    ?,
                    'ITEM_CRIADO',
                    'DISPONIVEL',
                    'SISTEMA',
                    'SISTEMA',
                    'Item criado antes da migration 002.'
                );
                """,
                (id_item,),
            )

            conn.commit()

        finally:
            conn.close()

    def test_cria_tabela_usuarios_e_registra_migration(self) -> None:
        """Valida a nova entidade e o registro da versão aplicada."""

        colunas = {
            registro[1]
            for registro in self.conn.execute(
                "PRAGMA table_info(usuarios);"
            ).fetchall()
        }

        self.assertEqual(
            colunas,
            {
                "id",
                "matricula",
                "nome",
                "ativo",
                "criado_em",
                "atualizado_em",
            },
        )

        migration = self.conn.execute(
            """
            SELECT version, nome
            FROM schema_migrations
            WHERE version = 2;
            """
        ).fetchone()

        self.assertEqual(
            migration,
            (
                2,
                "002_cria_usuarios_e_relacionamentos",
            ),
        )

    def test_valida_matricula_nome_atividade_e_unicidade(self) -> None:
        """Protege as regras estruturais do cadastro de usuários."""

        self.conn.execute(
            """
            INSERT INTO usuarios (matricula, nome)
            VALUES ('CA049341', 'CARLOS ALBERTO');
            """
        )

        comandos_invalidos = [
            (
                """
                INSERT INTO usuarios (matricula, nome)
                VALUES ('CA049341', 'OUTRO USUARIO');
                """,
                (),
            ),
            (
                """
                INSERT INTO usuarios (matricula, nome)
                VALUES ('C049341', 'MATRICULA INVALIDA');
                """,
                (),
            ),
            (
                """
                INSERT INTO usuarios (matricula, nome)
                VALUES ('ca049341', 'MATRICULA MINUSCULA');
                """,
                (),
            ),
            (
                """
                INSERT INTO usuarios (matricula, nome)
                VALUES ('AB123456', '   ');
                """,
                (),
            ),
            (
                """
                INSERT INTO usuarios (matricula, nome, ativo)
                VALUES ('AB123456', 'USUARIO', 'TALVEZ');
                """,
                (),
            ),
        ]

        for sql, parametros in comandos_invalidos:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql, parametros)

    def test_relacionamentos_humanos_apontam_para_usuarios(self) -> None:
        """Confirma no catálogo do SQLite as quatro FKs humanas."""

        relacionamentos = {
            "plano_parametrizacao": (
                "ativado_por",
                "matricula",
            ),
            "plano_parametrizacao_item": (
                "controlador_responsavel",
                "matricula",
            ),
            "parametrizacao_decisao": (
                "controlador",
                "matricula",
            ),
            "parametrizacao_historico": (
                "usuario_matricula",
                "matricula",
            ),
        }

        for tabela, relacao_esperada in relacionamentos.items():
            with self.subTest(tabela=tabela):
                fks = self.conn.execute(
                    f"PRAGMA foreign_key_list({tabela});"
                ).fetchall()

                relacoes_usuarios = {
                    (fk[3], fk[4])
                    for fk in fks
                    if fk[2] == "usuarios"
                }

                self.assertIn(
                    relacao_esperada,
                    relacoes_usuarios,
                )

    def test_preserva_dados_anteriores_e_integridade(self) -> None:
        """Garante que reconstruir tabelas não perde registros legados."""

        contagens = {
            "plano_parametrizacao": 1,
            "plano_parametrizacao_item": 1,
            "parametrizacao_decisao": 0,
            "parametrizacao_confirmacao": 0,
            "parametrizacao_historico": 1,
        }

        for tabela, quantidade_esperada in contagens.items():
            with self.subTest(tabela=tabela):
                quantidade = self.conn.execute(
                    f"SELECT COUNT(*) FROM {tabela};"
                ).fetchone()[0]

                self.assertEqual(
                    quantidade,
                    quantidade_esperada,
                )

        historico = self.conn.execute(
            """
            SELECT usuario, usuario_matricula
            FROM parametrizacao_historico;
            """
        ).fetchone()

        self.assertEqual(
            historico,
            ("SISTEMA", None),
        )

        erros_fk = self.conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        self.assertEqual(erros_fk, [])

    def test_rejeita_referencias_a_usuario_inexistente(self) -> None:
        """Comprova que as FKs bloqueiam matrículas não cadastradas."""

        id_plano = self.conn.execute(
            "SELECT id FROM plano_parametrizacao;"
        ).fetchone()[0]

        id_item = self.conn.execute(
            "SELECT id FROM plano_parametrizacao_item;"
        ).fetchone()[0]

        comandos_invalidos = [
            (
                """
                UPDATE plano_parametrizacao
                SET ativado_por = 'ZZ999999'
                WHERE id = ?;
                """,
                (id_plano,),
            ),
            (
                """
                UPDATE plano_parametrizacao_item
                SET controlador_responsavel = 'ZZ999999'
                WHERE id = ?;
                """,
                (id_item,),
            ),
            (
                """
                UPDATE parametrizacao_historico
                SET usuario_matricula = 'ZZ999999'
                WHERE id_item_plano = ?;
                """,
                (id_item,),
            ),
        ]

        for sql, parametros in comandos_invalidos:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql, parametros)


if __name__ == "__main__":
    unittest.main()
