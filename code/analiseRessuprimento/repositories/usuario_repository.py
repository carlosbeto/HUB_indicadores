from __future__ import annotations

import sqlite3
from typing import Any


def obter_usuario_por_matricula(
    conn: sqlite3.Connection,
    *,
    matricula: str,
) -> dict[str, Any] | None:
    """Retorna um usuário pelo identificador corporativo.

    O repository conhece apenas a persistência: ele consulta a matrícula
    recebida exatamente como foi informada e não decide se o usuário pode
    operar o aplicativo. Normalização, formato e atividade são regras da
    camada de serviço.

    O retorno em dicionário mantém um contrato explícito com os nomes dos
    campos. Assim, a camada chamadora não fica dependente da posição das
    colunas no SELECT.
    """

    cursor = conn.execute(
        """
        SELECT
            id,
            matricula,
            nome,
            ativo,
            criado_em,
            atualizado_em
        FROM usuarios
        WHERE matricula = ?
        """,
        (matricula,),
    )

    registro = cursor.fetchone()

    if registro is None:
        return None

    colunas = [
        descricao[0]
        for descricao in cursor.description
    ]

    return dict(
        zip(
            colunas,
            registro,
        )
    )
