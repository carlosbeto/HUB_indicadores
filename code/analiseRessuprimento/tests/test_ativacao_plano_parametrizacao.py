from __future__ import annotations

import sqlite3
import unittest

from services.plano_parametrizacao_service import (
    ativar_plano_parametrizacao,
)


class TestAtivacaoPlanoParametrizacao(unittest.TestCase):
    """Valida isoladamente a transição RASCUNHO para ATIVO."""

    def setUp(self) -> None:
        """Cria um banco mínimo com as mesmas relações da migration 002."""

        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")

        self.conn.execute(
            """
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                ativo TEXT NOT NULL CHECK (ativo IN ('SIM', 'NAO')),
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE plano_parametrizacao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_plano TEXT NOT NULL,
                onda TEXT NOT NULL,
                status_plano TEXT NOT NULL,
                ativado_por TEXT,
                ativado_em TEXT,

                FOREIGN KEY (ativado_por)
                    REFERENCES usuarios(matricula)
            )
            """
        )

        self.conn.executemany(
            """
            INSERT INTO usuarios (
                matricula,
                nome,
                ativo
            )
            VALUES (?, ?, ?)
            """,
            [
                (
                    "CA049341",
                    "CARLOS ALBERTO",
                    "SIM",
                ),
                (
                    "AB123456",
                    "USUARIO INATIVO",
                    "NAO",
                ),
            ],
        )

        self.conn.execute(
            """
            INSERT INTO plano_parametrizacao (
                nome_plano,
                onda,
                status_plano
            )
            VALUES ('Wave A', 'A', 'RASCUNHO')
            """
        )
        self.conn.commit()

    def tearDown(self) -> None:
        """Libera a conexão temporária ao final de cada cenário."""

        self.conn.close()

    def test_ativa_plano_rascunho_por_usuario_ativo(self) -> None:
        """Persiste estado, responsável e momento da ativação."""

        resultado = ativar_plano_parametrizacao(
            self.conn,
            id_plano=1,
            matricula=" ca049341 ",
        )

        self.assertEqual(resultado["id_plano"], 1)
        self.assertEqual(resultado["status"], "ATIVO")
        self.assertEqual(
            resultado["ativado_por"],
            "CA049341",
        )
        self.assertIsNotNone(resultado["ativado_em"])

    def test_rejeita_usuario_nao_cadastrado(self) -> None:
        """Impede ativação por uma matrícula apenas formalmente válida."""

        with self.assertRaisesRegex(
            ValueError,
            "Matrícula não cadastrada",
        ):
            ativar_plano_parametrizacao(
                self.conn,
                id_plano=1,
                matricula="ZZ999999",
            )

        status = self.conn.execute(
            """
            SELECT status_plano
            FROM plano_parametrizacao
            WHERE id = 1
            """
        ).fetchone()[0]

        self.assertEqual(status, "RASCUNHO")

    def test_rejeita_usuario_inativo(self) -> None:
        """Mantém o plano intacto quando o cadastro está inativo."""

        with self.assertRaisesRegex(
            ValueError,
            "Usuário inativo",
        ):
            ativar_plano_parametrizacao(
                self.conn,
                id_plano=1,
                matricula="AB123456",
            )

    def test_rejeita_plano_inexistente(self) -> None:
        """Diferencia identificador inexistente de estado inválido."""

        with self.assertRaisesRegex(
            ValueError,
            "Plano de parametrização não encontrado",
        ):
            ativar_plano_parametrizacao(
                self.conn,
                id_plano=999,
                matricula="CA049341",
            )

    def test_rejeita_segunda_ativacao(self) -> None:
        """A ativação é uma transição única, não uma edição repetível."""

        ativar_plano_parametrizacao(
            self.conn,
            id_plano=1,
            matricula="CA049341",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Somente um plano em rascunho",
        ):
            ativar_plano_parametrizacao(
                self.conn,
                id_plano=1,
                matricula="CA049341",
            )


if __name__ == "__main__":
    unittest.main()
