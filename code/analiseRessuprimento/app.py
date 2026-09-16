import streamlit as st

from db.connection import abrir_conexao
from repositories.usuario_repository import (
    obter_usuario_por_matricula,
)
from ui.parametrizacao import render_parametrizacao
from ui.risco_abastecimento_pcp import (
    render_risco_abastecimento_pcp,
)
from ui.ressuprimento_pt02 import render_ressuprimento_pt02


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

        # O menu separa dois processos relacionados, mas independentes:
        # o abastecimento diário do picking e a parametrização MIN/MAX.
        # Ressuprimento PT02 é a página inicial por ser a urgência operacional.
        st.sidebar.title("Análise de Ressuprimento")
        st.sidebar.caption(
            f"{usuario['nome']} — {usuario['matricula']}"
        )

        pagina = st.sidebar.radio(
            "Navegação",
            options=[
                "Ressuprimento PT02",
                "Risco de abastecimento — PCP",
                "Parametrização BINMAT",
            ],
            key="pagina_analise_ressuprimento",
        )

        if pagina == "Ressuprimento PT02":
            render_ressuprimento_pt02(
                conn,
                usuario=usuario,
            )
        elif pagina == "Risco de abastecimento — PCP":
            render_risco_abastecimento_pcp(
                conn,
                usuario=usuario,
            )
        else:
            # A fila BINMAT é reconstruída a partir dos relatórios atuais.
            # Não depende de plano, assunção de tarefa ou conclusão manual.
            render_parametrizacao(
                conn,
                usuario=usuario,
            )


if __name__ == "__main__":
    main()
