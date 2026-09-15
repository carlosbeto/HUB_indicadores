from __future__ import annotations

"""Testes da migration 003 que adiciona a UMB aos movimentos MB51."""

import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    BASE_DIR / "migrations" / "003_adiciona_umb_mb51.py"
)


def carregar_migration_003():
    """Carrega a migration numérica diretamente pelo caminho."""

    spec = importlib.util.spec_from_file_location(
        "migration_003_adiciona_umb_mb51",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar a migration 003.")

    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestMigration003UmbMb51(unittest.TestCase):
    """Protege estrutura, dados anteriores e repetibilidade."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "teste.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                nome TEXT NOT NULL,
                aplicado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_migrations (version, nome)
            VALUES
                (1, '001_cria_plano_parametrizacao'),
                (2, '002_cria_usuarios_e_relacionamentos');

            CREATE TABLE dim_material (
                material TEXT PRIMARY KEY
            );

            INSERT INTO dim_material (material)
            VALUES ('1111111');

            CREATE TABLE fact_mb51_movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT NOT NULL,
                data_lancamento TEXT NOT NULL,
                tipo_movimento TEXT NOT NULL,
                debito_credito TEXT,
                quantidade REAL NOT NULL,
                documento_material TEXT NOT NULL,
                item_documento TEXT NOT NULL,
                deposito TEXT,
                centro_custo TEXT,
                usuario TEXT,
                arquivo_origem TEXT NOT NULL,
                carregado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (documento_material, item_documento),
                FOREIGN KEY (material) REFERENCES dim_material(material)
            );

            INSERT INTO fact_mb51_movimentos (
                material,
                data_lancamento,
                tipo_movimento,
                debito_credito,
                quantidade,
                documento_material,
                item_documento,
                arquivo_origem
            )
            VALUES (
                '1111111', '2026-09-14', '601', 'H', -10,
                '500000001', '1', 'MB51_ANTIGA.xlsx'
            );
            """
        )
        self.conn.commit()
        self.conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_adiciona_coluna_sem_perder_movimentos(self) -> None:
        modulo = carregar_migration_003()
        modulo.aplicar_migration(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn:
            colunas = {
                linha[1]
                for linha in conn.execute(
                    "PRAGMA table_info(fact_mb51_movimentos);"
                )
            }
            movimento = conn.execute(
                """
                SELECT documento_material, quantidade, unidade_medida_basica
                FROM fact_mb51_movimentos;
                """
            ).fetchone()

        self.assertIn("unidade_medida_basica", colunas)
        self.assertEqual(movimento, ("500000001", -10.0, None))

    def test_registra_versao_003(self) -> None:
        modulo = carregar_migration_003()
        modulo.aplicar_migration(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn:
            registro = conn.execute(
                """
                SELECT version, nome
                FROM schema_migrations
                WHERE version = 3;
                """
            ).fetchone()

        self.assertEqual(registro, (3, "003_adiciona_umb_mb51"))

    def test_segunda_execucao_nao_altera_o_banco(self) -> None:
        modulo = carregar_migration_003()
        modulo.aplicar_migration(self.db_path)
        modulo.aplicar_migration(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn:
            quantidade_colunas = conn.execute(
                """
                SELECT COUNT(*)
                FROM pragma_table_info('fact_mb51_movimentos')
                WHERE name = 'unidade_medida_basica';
                """
            ).fetchone()[0]
            quantidade_versoes = conn.execute(
                """
                SELECT COUNT(*)
                FROM schema_migrations
                WHERE version = 3;
                """
            ).fetchone()[0]

        self.assertEqual(quantidade_colunas, 1)
        self.assertEqual(quantidade_versoes, 1)


if __name__ == "__main__":
    unittest.main()
