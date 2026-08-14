import socket
from pathlib import Path

import streamlit as st


def render(cfg=None):
    st.set_page_config(page_title="HUB - Inventários", layout="wide")
    st.title("Analise Inventários")

    host = socket.gethostname()
    url = f"http://{host}:8504/"

    st.info("Portal do HUB para Inventários. Este botão abre o app que roda na porta 8504.")

    st.link_button("Abrir Analise Inventários (porta 8504)", url)

    st.caption(f"Link direto: {url}")

    # Banco oficial utilizado pelo módulo de Inventários.
    try:
        db_abs = (
            Path(__file__).resolve().parents[3]
            / "code"
            / "analiseInventarios"
            / "data_db"
            / "inventarios.sqlite"
        ).resolve()

        st.caption(f"DB Inventários: {db_abs}")
        st.caption(f"Existe? {'SIM' if db_abs.exists() else 'NÃO'}")
    except Exception:
        pass