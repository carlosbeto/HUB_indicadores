import streamlit as st

from db.connection import abrir_conexao
from ui.parametrizacao import render_parametrizacao


ID_PLANO_INICIAL = 1


def main() -> None:
    st.set_page_config(
        page_title="Análise de Ressuprimento",
        page_icon="📦",
        layout="wide",
    )

    with abrir_conexao() as conn:
        render_parametrizacao(
            conn,
            id_plano=ID_PLANO_INICIAL,
        )


if __name__ == "__main__":
    main()
