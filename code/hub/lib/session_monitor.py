from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st


ACTIVE_WINDOW_MINUTES = 5
HEARTBEAT_SECONDS = 60


def _database_path() -> Path:
    """Retorna o banco local de telemetria na pasta de dados do HUB."""
    project_root = Path(__file__).resolve().parents[3]
    database_dir = project_root / "data" / "hub"
    database_dir.mkdir(parents=True, exist_ok=True)
    return database_dir / "sessoes.sqlite"


def _connect(database_path: Path | None = None) -> sqlite3.Connection:
    path = database_path or _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hub_sessao (
            session_id TEXT PRIMARY KEY,
            iniciada_em TEXT NOT NULL,
            ultima_atividade_em TEXT NOT NULL,
            pagina_atual TEXT NOT NULL
        )
        """
    )
    return connection


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def registrar_atividade(
    session_id: str,
    pagina: str,
    *,
    agora: datetime | None = None,
    database_path: Path | None = None,
) -> int:
    """Registra a atividade e devolve a quantidade de sessões ativas."""
    instante = agora or _agora_utc()
    instante_iso = instante.isoformat(timespec="seconds")
    limite_ativo = (instante - timedelta(minutes=ACTIVE_WINDOW_MINUTES)).isoformat(
        timespec="seconds"
    )
    limite_limpeza = (instante - timedelta(days=2)).isoformat(timespec="seconds")

    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO hub_sessao (
                session_id,
                iniciada_em,
                ultima_atividade_em,
                pagina_atual
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                ultima_atividade_em = excluded.ultima_atividade_em,
                pagina_atual = excluded.pagina_atual
            """,
            (session_id, instante_iso, instante_iso, pagina),
        )
        connection.execute(
            "DELETE FROM hub_sessao WHERE ultima_atividade_em < ?",
            (limite_limpeza,),
        )
        quantidade = connection.execute(
            """
            SELECT COUNT(*)
            FROM hub_sessao
            WHERE ultima_atividade_em >= ?
            """,
            (limite_ativo,),
        ).fetchone()[0]

    return int(quantidade)


def _session_id() -> str:
    if "hub_anonymous_session_id" not in st.session_state:
        st.session_state["hub_anonymous_session_id"] = uuid.uuid4().hex
    return str(st.session_state["hub_anonymous_session_id"])


def render_session_counter(pagina: str) -> None:
    """Exibe na barra lateral o contador anônimo de sessões ativas."""

    @st.fragment(run_every=HEARTBEAT_SECONDS)
    def _heartbeat() -> None:
        try:
            quantidade = registrar_atividade(_session_id(), pagina)
        except sqlite3.Error:
            # O monitoramento é acessório e nunca deve impedir o uso do HUB.
            st.caption("Sessões ativas: indisponível")
            return

        st.metric(
            "Sessões ativas agora",
            quantidade,
            help=(
                "Sessões com atividade nos últimos 5 minutos. "
                "Uma pessoa com várias abas pode aparecer mais de uma vez."
            ),
        )

    # Fragmentos não podem chamar st.sidebar internamente. A execução do
    # fragmento deve ocorrer dentro do contexto da barra lateral.
    with st.sidebar:
        _heartbeat()
