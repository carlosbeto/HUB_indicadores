from pathlib import Path
import sqlite3
import tempfile
import unittest


class TestConnection(unittest.TestCase):

    def test_abre_conexao_com_foreign_keys_ativas(self):
        from db.connection import abrir_conexao

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "teste.sqlite"

            conn = abrir_conexao(db_path)

            try:
                foreign_keys = conn.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0]

                self.assertEqual(
                    foreign_keys,
                    1,
                )

                self.assertIsInstance(
                    conn,
                    sqlite3.Connection,
                )

            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
