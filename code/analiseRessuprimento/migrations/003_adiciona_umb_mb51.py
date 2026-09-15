from __future__ import annotations

"""
Migration 003 - unidade de medida básica dos movimentos MB51.

A coluna ``quantidade`` da fato é carregada do campo ``Quantidade`` do
relatório SAP. A unidade semanticamente correspondente a esse valor é a
``UMB`` (unidade de medida básica), e não a ``UM registro``.

Esta migration acrescenta apenas um atributo à entidade movimento. Não há
novo relacionamento E/R porque a unidade descreve a própria quantidade do
fato. Os valores históricos permanecem nulos até a execução controlada do
retropreenchimento baseado no MB51 acumulado.
"""

import sqlite3
from pathlib import Path


MIGRATION_VERSION = 3
MIGRATION_NAME = "003_adiciona_umb_mb51"

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"


def _migration_registrada(conn: sqlite3.Connection) -> bool:
    """Informa se a versão 003 já foi aplicada."""

    registro = conn.execute(
        """
        SELECT 1
        FROM schema_migrations
        WHERE version = ?
        LIMIT 1;
        """,
        (MIGRATION_VERSION,),
    ).fetchone()
    return registro is not None


def _coluna_existe(conn: sqlite3.Connection, coluna: str) -> bool:
    """Consulta as colunas atuais da fato sem modificar o schema."""

    colunas = {
        linha[1]
        for linha in conn.execute(
            "PRAGMA table_info(fact_mb51_movimentos);"
        ).fetchall()
    }
    return coluna in colunas


def _validar_estado_inicial(conn: sqlite3.Connection) -> None:
    """Impede aplicação sobre banco incompleto ou fora de sequência."""

    tabelas = {
        linha[0]
        for linha in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table';
            """
        ).fetchall()
    }

    obrigatorias = {"schema_migrations", "fact_mb51_movimentos"}
    ausentes = sorted(obrigatorias - tabelas)
    if ausentes:
        raise RuntimeError(
            "Tabelas obrigatórias ausentes antes da migration 003: "
            + ", ".join(ausentes)
        )

    versoes = {
        linha[0]
        for linha in conn.execute(
            "SELECT version FROM schema_migrations;"
        ).fetchall()
    }
    if not {1, 2}.issubset(versoes):
        raise RuntimeError(
            "As migrations 001 e 002 devem estar aplicadas antes da 003."
        )


def aplicar_migration(db_path: Path | str | None = None) -> None:
    """Aplica a alteração de forma atômica e idempotente."""

    banco = Path(db_path) if db_path is not None else DB_PATH
    if not banco.exists():
        raise FileNotFoundError(
            "Banco SQLite não encontrado. "
            f"Caminho esperado: {banco}"
        )

    conn = sqlite3.connect(banco)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        if _migration_registrada(conn):
            print("Migration 003 já está registrada no banco.")
            print("Nenhuma alteração foi realizada.")
            return

        _validar_estado_inicial(conn)
        conn.execute("BEGIN IMMEDIATE;")

        if not _coluna_existe(conn, "unidade_medida_basica"):
            conn.execute(
                """
                ALTER TABLE fact_mb51_movimentos
                ADD COLUMN unidade_medida_basica TEXT;
                """
            )

        conn.execute(
            """
            INSERT INTO schema_migrations (version, nome)
            VALUES (?, ?);
            """,
            (MIGRATION_VERSION, MIGRATION_NAME),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    aplicar_migration()
