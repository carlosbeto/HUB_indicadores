import streamlit as st

from db.connection import abrir_conexao
from repositories.usuario_repository import (
    obter_usuario_por_matricula,
)
from ui.parametrizacao import render_parametrizacao


ID_PLANO_INICIAL = 1

# Identidade operacional provisória para a demonstração inicial do workflow.
#
# A matrícula não substitui um login completo. Ela apenas permite que todas
# as ações humanas já nasçam vinculadas a um usuário válido do modelo E/R.
# Quando a tela de identificação for criada, esta constante será substituída
# pelo usuário guardado na sessão do Streamlit.
MATRICULA_USUARIO_INICIAL = "CA049341"


def main() -> None:
    st.set_page_config(
        page_title="Análise de Ressuprimento",
        page_icon="📦",
        layout="wide",
    )

    with abrir_conexao() as conn:
        # O aplicativo não confia somente na constante acima: antes de
        # apresentar qualquer ação, confirma no banco que a matrícula existe
        # e que o cadastro continua ativo.
        usuario = obter_usuario_por_matricula(
            conn,
            matricula=MATRICULA_USUARIO_INICIAL,
        )

        if usuario is None:
            st.error(
                "O usuário operacional não está cadastrado."
            )
            st.stop()

        if usuario["ativo"] != "SIM":
            st.error(
                "O usuário operacional está inativo."
            )
            st.stop()

        render_parametrizacao(
            conn,
            id_plano=ID_PLANO_INICIAL,
            usuario=usuario,
        )


if __name__ == "__main__":
    main()
