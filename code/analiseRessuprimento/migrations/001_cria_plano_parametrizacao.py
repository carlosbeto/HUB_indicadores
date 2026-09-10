from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


# ============================================================
# IDENTIFICAÇÃO DA MIGRATION
# ============================================================

MIGRATION_VERSION = 1
MIGRATION_NAME = "001_cria_plano_parametrizacao"


# ============================================================
# CAMINHOS
# ============================================================
#
# Arquivo:
#
# code\analiseRessuprimento\migrations\
#     001_cria_plano_parametrizacao.py
#
# BASE_DIR aponta para:
#
# code\analiseRessuprimento
#
# O caminho do próprio módulo é incluído no sys.path para
# permitir a importação de db.schema quando a migration for
# executada diretamente como script.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


from db.schema import (  # noqa: E402
    criar_schema_migrations,
    criar_schema_plano_parametrizacao,
)


# ============================================================
# TABELAS CRIADAS POR ESTA MIGRATION
# ============================================================

TABELAS_MIGRATION = {
    "plano_parametrizacao",
    "plano_parametrizacao_item",
    "parametrizacao_decisao",
    "parametrizacao_confirmacao",
    "parametrizacao_historico",
}


def tabela_existe(conn: sqlite3.Connection, nome_tabela: str) -> bool:
    """
    Verifica se uma tabela existe no banco SQLite.
    """

    registro = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1;
        """,
        (nome_tabela,),
    ).fetchone()

    return registro is not None


def migration_ja_aplicada(conn: sqlite3.Connection) -> bool:
    """
    Retorna True se esta migration já estiver registrada.
    """

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


def validar_estado_inicial(conn: sqlite3.Connection) -> None:
    """
    Impede a execução em um banco estruturalmente ambíguo.

    Se a migration 001 ainda não estiver registrada, nenhuma
    das cinco tabelas pertencentes a ela deveria existir.
    """

    tabelas_existentes = sorted(
        tabela
        for tabela in TABELAS_MIGRATION
        if tabela_existe(conn, tabela)
    )

    if tabelas_existentes:
        lista = ", ".join(tabelas_existentes)

        raise RuntimeError(
            "Migration 001 ainda não registrada, porém já existem "
            f"tabelas pertencentes a ela: {lista}. "
            "A execução foi interrompida para evitar assumir "
            "um schema parcial ou divergente."
        )


def registrar_migration(conn: sqlite3.Connection) -> None:
    """
    Registra a migration somente após toda a estrutura ter sido
    criada com sucesso.
    """

    conn.execute(
        """
        INSERT INTO schema_migrations (
            version,
            nome
        )
        VALUES (?, ?);
        """,
        (
            MIGRATION_VERSION,
            MIGRATION_NAME,
        ),
    )


def aplicar_migration(
    db_path: Path | None = None,
) -> None:
    """
    Aplica a migration 001 de forma transacional.

    O DDL das tabelas fica centralizado em db.schema.
    Esta função controla somente:

    - conexão;
    - transação;
    - validação;
    - registro da migration;
    - commit/rollback.
    """

    banco = db_path if db_path is not None else DB_PATH

    print("=" * 72)
    print("MIGRATION 001 - PLANO DE PARAMETRIZACAO")
    print("=" * 72)
    print(f"Banco: {banco}")
    print()

    if not banco.exists():
        raise FileNotFoundError(
            "Banco SQLite não encontrado. "
            f"Caminho esperado: {banco}"
        )

    conn = sqlite3.connect(banco)

    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        foreign_keys = conn.execute(
            "PRAGMA foreign_keys;"
        ).fetchone()[0]

        if foreign_keys != 1:
            raise RuntimeError(
                "Não foi possível ativar PRAGMA foreign_keys."
            )

        conn.execute("BEGIN IMMEDIATE;")

        criar_schema_migrations(conn)

        if migration_ja_aplicada(conn):
            conn.rollback()

            print(
                f"Migration {MIGRATION_VERSION:03d} "
                "já está registrada no banco."
            )
            print("Nenhuma alteração foi realizada.")
            return

        validar_estado_inicial(conn)

        criar_schema_plano_parametrizacao(conn)

        registrar_migration(conn)

        conn.commit()

        print("Migration aplicada com sucesso.")
        print()
        print("Criado:")
        print("  - schema_migrations")
        print("  - plano_parametrizacao")
        print("  - plano_parametrizacao_item")
        print("  - parametrizacao_decisao")
        print("  - parametrizacao_confirmacao")
        print("  - parametrizacao_historico")
        print()
        print(
            f"Versão registrada: "
            f"{MIGRATION_VERSION:03d} - {MIGRATION_NAME}"
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    print()
    print("=" * 72)


if __name__ == "__main__":
    aplicar_migration()
