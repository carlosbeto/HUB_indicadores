from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"


def abrir_conexao(
    db_path: Path | str = DB_PATH,
) -> sqlite3.Connection:
    """
    Abre uma conexão SQLite do módulo de Ressuprimento.

    Foreign keys são ativadas explicitamente em cada conexão,
    pois essa configuração é específica da conexão no SQLite.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    return conn
