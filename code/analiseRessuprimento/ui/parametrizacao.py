import sqlite3

import streamlit as st

from repositories.plano_parametrizacao_repository import (
    listar_fila_operacional_plano,
    obter_resumo_operacional_plano,
)

from services.plano_parametrizacao_service import (
    assumir_tarefa,
    ativar_plano_parametrizacao,
    liberar_tarefa,
    obter_detalhe_operacional_tarefa,
)


def _obter_acoes_tarefa(
    *,
    status_plano: str,
    status_item: str,
    controlador_responsavel: str | None,
    matricula_usuario: str,
) -> dict[str, bool]:
    """Informa quais comandos a interface pode apresentar ao usuário.

    Esta função não grava dados. Ela apenas traduz os estados do workflow em
    visibilidade dos botões. O service repete todas as validações no momento
    da escrita, protegendo o banco mesmo que duas pessoas atuem ao mesmo tempo.
    """

    plano_ativo = status_plano == "ATIVO"

    return {
        "assumir": (
            plano_ativo
            and status_item == "DISPONIVEL"
            and controlador_responsavel is None
        ),
        "liberar": (
            plano_ativo
            and status_item == "EM_ANALISE"
            and controlador_responsavel == matricula_usuario
        ),
    }


def render_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
    usuario: dict,
) -> None:
    """Renderiza a parametrização e as ações permitidas no estado atual.

    O usuário chega validado por ``app.py``. A camada de serviço ainda repete
    a validação no momento da escrita, pois uma interface nunca deve ser a
    única proteção de uma regra de negócio.
    """

    plano = obter_resumo_operacional_plano(
        conn,
        id_plano=id_plano,
    )

    if plano is None:
        st.error(
            f"Plano {id_plano} não encontrado."
        )
        return

    fila = listar_fila_operacional_plano(
        conn,
        id_plano=id_plano,
    )

    st.title("Parametrização PT02")

    # A identidade fica visível durante toda a operação. Isso reduz o risco
    # de uma ação ser executada sem que o controlador perceba qual matrícula
    # será registrada no banco.
    st.caption(
        f"Usuário: {usuario['nome']} — {usuario['matricula']}"
    )

    st.caption(
        f"Plano: {plano['nome']} | "
        f"Onda: {plano['onda']} | "
        f"Status: {plano['status']}"
    )

    # A mensagem é colocada na sessão antes do rerun. Sem esse pequeno estado
    # temporário, o Streamlit reconstruiria a página após a ativação e a
    # confirmação de sucesso desapareceria imediatamente.
    chave_mensagem = f"mensagem_ativacao_plano_{id_plano}"
    mensagem_ativacao = st.session_state.pop(
        chave_mensagem,
        None,
    )

    if mensagem_ativacao is not None:
        st.success(mensagem_ativacao)

    # A confirmação de uma tarefa assumida também precisa sobreviver ao
    # rerun que atualiza a fila. A chave é independente da ativação porque
    # cada mensagem representa uma ação operacional diferente.
    chave_mensagem_tarefa = "mensagem_workflow_parametrizacao"
    mensagem_tarefa = st.session_state.pop(
        chave_mensagem_tarefa,
        None,
    )

    if mensagem_tarefa is not None:
        st.success(mensagem_tarefa)

    if plano["status"] == "RASCUNHO":
        st.warning(
            "A Wave A ainda está em rascunho. Ative o plano para "
            "iniciar o workflow operacional."
        )

        # A confirmação separada protege uma transição que não deve ocorrer
        # por um clique acidental durante a navegação ou demonstração.
        confirmou_ativacao = st.checkbox(
            "Confirmo a ativação da Wave A.",
            key=f"confirmar_ativacao_plano_{id_plano}",
        )

        ativar = st.button(
            "Ativar Wave A",
            type="primary",
            disabled=not confirmou_ativacao,
            key=f"ativar_plano_{id_plano}",
        )

        if ativar:
            try:
                # A interface apenas solicita a transição. Validação do
                # usuário, estado do plano, concorrência, commit e rollback
                # permanecem centralizados no service.
                ativar_plano_parametrizacao(
                    conn,
                    id_plano=id_plano,
                    matricula=usuario["matricula"],
                )

            except ValueError as erro:
                st.error(str(erro))

            else:
                st.session_state[chave_mensagem] = (
                    "Wave A ativada com sucesso."
                )
                st.rerun()

    st.subheader("Fila operacional")

    if not fila:
        st.info(
            "Nenhum item encontrado para este plano."
        )
        return

    evento = st.dataframe(
        fila,
        width="stretch",
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="fila_operacional",
    )

    linhas_selecionadas = evento.selection.rows

    if not linhas_selecionadas:
        st.info(
            "Selecione um material na fila para visualizar "
            "o detalhe operacional."
        )
        return

    indice_selecionado = linhas_selecionadas[0]

    item_selecionado = fila[indice_selecionado]

    id_item_plano = item_selecionado["id_item_plano"]

    detalhe = obter_detalhe_operacional_tarefa(
        conn,
        id_item_plano=id_item_plano,
    )

    item = detalhe["item"]
    snapshot = detalhe["snapshot_inicial"]
    binmat = detalhe["binmat_atual"]
    decisao = detalhe["decisao_ativa"]
    confirmacao = detalhe["ultima_confirmacao_sap"]

    st.divider()

    st.subheader(
        f"Detalhe operacional — {item['material']}"
    )

    st.caption(
        f"{item['descricao']} | "
        f"PT02: {item['posicao_pt02']} | "
        f"Prioridade: {item['prioridade']} | "
        f"Status: {item['status']}"
    )

    # --------------------------------------------------------
    # PRIMEIRO COMANDO OPERACIONAL: ASSUMIR TAREFA
    # --------------------------------------------------------
    # O botão somente aparece quando as duas condições de negócio já estão
    # visíveis na tela: plano ativo e item disponível. Mesmo assim, o service
    # repete essas validações dentro de uma transação, pois o estado pode mudar
    # entre a renderização da página e o clique do usuário.
    acoes = _obter_acoes_tarefa(
        status_plano=detalhe["plano"]["status"],
        status_item=item["status"],
        controlador_responsavel=item["controlador_responsavel"],
        matricula_usuario=usuario["matricula"],
    )

    if acoes["assumir"]:
        if st.button(
            "Assumir tarefa",
            type="primary",
            key=f"assumir_tarefa_{id_item_plano}",
        ):
            try:
                assumir_tarefa(
                    conn,
                    id_item_plano=id_item_plano,
                    controlador=usuario["matricula"],
                )

            except ValueError as erro:
                # Erros de domínio são apresentados sem detalhes técnicos.
                # Exemplos: outro controlador assumiu primeiro ou o plano
                # deixou de estar ativo antes do clique.
                st.error(str(erro))

            else:
                st.session_state[chave_mensagem_tarefa] = (
                    f"Tarefa do material {item['material']} "
                    "assumida com sucesso."
                )
                st.rerun()

    elif item["status"] == "EM_ANALISE":
        if acoes["liberar"]:
            st.success(
                "Esta tarefa está sob sua responsabilidade."
            )

            # Liberar não apaga histórico: o service registra a transição e
            # devolve a tarefa à fila para que outro controlador possa assumir.
            if st.button(
                "Liberar tarefa",
                key=f"liberar_tarefa_{id_item_plano}",
            ):
                try:
                    liberar_tarefa(
                        conn,
                        id_item_plano=id_item_plano,
                        controlador=usuario["matricula"],
                    )

                except ValueError as erro:
                    st.error(str(erro))

                else:
                    st.session_state[chave_mensagem_tarefa] = (
                        f"Tarefa do material {item['material']} "
                        "liberada com sucesso."
                    )
                    st.rerun()
        else:
            st.info(
                "Esta tarefa está em análise por outro controlador."
            )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Demanda relevante",
            snapshot["demanda_relevante"],
        )

        st.metric(
            "Demanda comercial",
            snapshot["demanda_comercial"],
        )

        st.metric(
            "Demanda técnica",
            snapshot["demanda_tecnica"],
        )

    with col2:
        st.metric(
            "Saldo PT02 F5",
            snapshot["saldo_pt02_f5"],
        )

        st.metric(
            "Saldo T001 F5",
            snapshot["saldo_t001_f5"],
        )

        st.metric(
            "Qtd. posições T001",
            snapshot["qtd_posicoes_t001"],
        )

    with col3:
        st.metric(
            "MIN inicial",
            snapshot["min"],
        )

        st.metric(
            "MAX inicial",
            snapshot["max"],
        )

        st.metric(
            "% demanda acumulada",
            snapshot["pct_demanda_acumulada"],
        )

    st.write(
        "**Situação física inicial:** "
        f"{snapshot['situacao_fisica']}"
    )

    st.markdown("### BINMAT atual")

    if binmat["presente"]:
        st.write(
            f"MIN atual: **{binmat['min']}**  \n"
            f"MAX atual: **{binmat['max']}**  \n"
            f"Arquivo origem: `{binmat['arquivo_origem']}`"
        )
    else:
        st.warning(
            "A posição não está presente no snapshot BINMAT atual."
        )

    st.markdown("### Decisão")

    if decisao is None:
        st.info(
            "Este item ainda não possui decisão ativa."
        )
    else:
        st.write(
            f"Decisão: **{decisao['decisao']}**  \n"
            f"Revisão: **{decisao['numero_revisao']}**  \n"
            f"MIN proposto: **{decisao['min_proposto']}**  \n"
            f"MAX proposto: **{decisao['max_proposto']}**"
        )

    st.markdown("### Última confirmação SAP")

    if confirmacao is None:
        st.info(
            "Ainda não há confirmação SAP registrada."
        )
    else:
        st.write(
            f"Resultado: **{confirmacao['resultado']}**  \n"
            f"MIN encontrado: **{confirmacao['min_encontrado']}**  \n"
            f"MAX encontrado: **{confirmacao['max_encontrado']}**  \n"
            f"Verificado em: **{confirmacao['verificado_em']}**"
        )
