from __future__ import annotations

import math
import sqlite3

import pandas as pd

from repositories.plano_parametrizacao_repository import (
    atualizar_status_item_apos_decisao,
    inserir_decisao_parametrizacao,
    inserir_historico_parametrizacao,
    inserir_item_plano_parametrizacao,
    inserir_plano_parametrizacao,
    obter_item_plano_por_id,
    tentar_assumir_item_plano,
    tentar_liberar_item_plano,
    inativar_decisao_ativa_item,
    obter_decisao_ativa_item,
)


STATUS_PLANO_INICIAL = "RASCUNHO"
STATUS_ITEM_INICIAL = "DISPONIVEL"
USUARIO_CRIACAO_PADRAO = "SISTEMA"

CRITERIO_PRIORIDADE = "DEMANDA_RELEVANTE_DESC"


# ============================================================
# NORMALIZAÇÃO DE VALORES
# ============================================================

def _valor_sql(
    valor,
):
    """
    Converte valores pandas/NumPy ausentes em NULL do SQLite.

    Mantém valores válidos sem alteração.
    """

    if valor is None:
        return None

    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass

    return valor


def _float_sql(
    valor,
) -> float | None:
    """
    Converte valor numérico para float ou NULL.
    """

    valor = _valor_sql(valor)

    if valor is None:
        return None

    numero = float(valor)

    if not math.isfinite(numero):
        return None

    return numero


def _int_sql(
    valor,
) -> int | None:
    """
    Converte valor numérico para inteiro ou NULL.
    """

    valor = _valor_sql(valor)

    if valor is None:
        return None

    return int(valor)


# ============================================================
# VALIDAÇÃO DO SNAPSHOT
# ============================================================

def _validar_snapshot_plano(
    df_snapshot: pd.DataFrame,
) -> None:
    """
    Valida se o snapshot possui os dados mínimos necessários
    para persistir uma onda de parametrização.
    """

    if df_snapshot is None:
        raise ValueError(
            "O snapshot da onda não foi informado."
        )

    if df_snapshot.empty:
        raise ValueError(
            "O snapshot da onda está vazio."
        )

    colunas_obrigatorias = {
        "prioridade",
        "material",
        "posicao",
        "descricao_material",
        "demanda_comercial",
        "demanda_tecnica",
        "demanda_relevante",
        "pct_demanda_acumulada",
        "quantidade_minima",
        "quantidade_maxima",
        "saldo_pt02_f5",
        "saldo_pt02_b5",
        "saldo_t001_f5",
        "saldo_t001_b5",
        "qtd_posicoes_t001",
        "situacao_fisica",
    }

    colunas_ausentes = (
        colunas_obrigatorias
        - set(df_snapshot.columns)
    )

    if colunas_ausentes:
        raise ValueError(
            "O snapshot não possui as colunas obrigatórias: "
            + ", ".join(
                sorted(colunas_ausentes)
            )
        )

    if df_snapshot.duplicated(
        subset=[
            "material",
            "posicao",
        ]
    ).any():
        raise ValueError(
            "O snapshot possui material + posição PT02 duplicados."
        )

    if df_snapshot["prioridade"].isna().any():
        raise ValueError(
            "O snapshot possui prioridade ausente."
        )

    if df_snapshot["material"].isna().any():
        raise ValueError(
            "O snapshot possui material ausente."
        )

    if df_snapshot["posicao"].isna().any():
        raise ValueError(
            "O snapshot possui posição PT02 ausente."
        )

    if (
        pd.to_numeric(
            df_snapshot["demanda_relevante"],
            errors="coerce",
        )
        .fillna(0.0)
        .le(0)
        .any()
    ):
        raise ValueError(
            "Todos os itens do plano devem possuir "
            "demanda relevante positiva."
        )


# ============================================================
# PERSISTÊNCIA DO PLANO
# ============================================================

def criar_plano_parametrizacao(
    conn: sqlite3.Connection,
    *,
    df_snapshot: pd.DataFrame,
    nome_plano: str,
    onda: str,
    data_inicio_demanda: str,
    data_fim_demanda: str,
    meses_demanda: int,
    percentual_alvo_demanda: float,
    demanda_total_backlog_origem: float,
    criado_por: str = USUARIO_CRIACAO_PADRAO,
    observacao: str | None = None,
) -> dict:
    """
    Persiste uma onda de parametrização de forma atômica.

    Fluxo:
    1. valida o snapshot;
    2. cria o cabeçalho do plano;
    3. cria os itens do plano;
    4. registra ITEM_CRIADO para cada item;
    5. confirma a transação somente ao final.

    Em qualquer erro, toda a operação é desfeita.
    """

    _validar_snapshot_plano(
        df_snapshot
    )

    if not nome_plano.strip():
        raise ValueError(
            "O nome do plano é obrigatório."
        )

    if not onda.strip():
        raise ValueError(
            "A identificação da onda é obrigatória."
        )

    if meses_demanda <= 0:
        raise ValueError(
            "meses_demanda deve ser maior que zero."
        )

    if (
        percentual_alvo_demanda <= 0
        or percentual_alvo_demanda > 100
    ):
        raise ValueError(
            "percentual_alvo_demanda deve estar "
            "entre 0 e 100."
        )

    df_persistencia = (
        df_snapshot
        .sort_values(
            by=[
                "prioridade",
                "material",
                "posicao",
            ],
            ascending=True,
        )
        .reset_index(drop=True)
    )

    quantidade_materiais = int(
        len(df_persistencia)
    )

    demanda_total_plano = float(
        pd.to_numeric(
            df_persistencia[
                "demanda_relevante"
            ],
            errors="coerce",
        ).sum()
    )

    percentual_real_cobertura = (
        demanda_total_plano
        / float(
            demanda_total_backlog_origem
        )
        * 100.0
    )

    ids_itens: list[int] = []

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        id_plano = inserir_plano_parametrizacao(
            conn,
            nome_plano=nome_plano,
            onda=onda,
            data_inicio_demanda=data_inicio_demanda,
            data_fim_demanda=data_fim_demanda,
            meses_demanda=meses_demanda,
            criterio_prioridade=CRITERIO_PRIORIDADE,
            percentual_alvo_demanda=float(
                percentual_alvo_demanda
            ),
            quantidade_materiais=(
                quantidade_materiais
            ),
            demanda_total_plano=(
                demanda_total_plano
            ),
            demanda_total_backlog_origem=float(
                demanda_total_backlog_origem
            ),
            percentual_real_cobertura=(
                percentual_real_cobertura
            ),
            status_plano=STATUS_PLANO_INICIAL,
            criado_por=criado_por,
            observacao=observacao,
        )

        for _, linha in df_persistencia.iterrows():
            id_item = inserir_item_plano_parametrizacao(
                conn,
                id_plano=id_plano,
                material=str(
                    linha["material"]
                ),
                posicao_pt02=str(
                    linha["posicao"]
                ),
                descricao_material=_valor_sql(
                    linha[
                        "descricao_material"
                    ]
                ),
                prioridade_inicial=int(
                    linha["prioridade"]
                ),
                demanda_comercial_inicial=float(
                    linha[
                        "demanda_comercial"
                    ]
                ),
                demanda_tecnica_inicial=float(
                    linha[
                        "demanda_tecnica"
                    ]
                ),
                demanda_relevante_inicial=float(
                    linha[
                        "demanda_relevante"
                    ]
                ),
                pct_demanda_acumulada_inicial=float(
                    linha[
                        "pct_demanda_acumulada"
                    ]
                ),
                min_inicial=_float_sql(
                    linha[
                        "quantidade_minima"
                    ]
                ),
                max_inicial=_float_sql(
                    linha[
                        "quantidade_maxima"
                    ]
                ),
                saldo_pt02_f5_inicial=_float_sql(
                    linha[
                        "saldo_pt02_f5"
                    ]
                ),
                saldo_pt02_b5_inicial=_float_sql(
                    linha[
                        "saldo_pt02_b5"
                    ]
                ),
                saldo_t001_f5_inicial=(
                    _float_sql(
                        linha[
                            "saldo_t001_f5"
                        ]
                    )
                    or 0.0
                ),
                saldo_t001_b5_inicial=(
                    _float_sql(
                        linha[
                            "saldo_t001_b5"
                        ]
                    )
                    or 0.0
                ),
                qtd_posicoes_t001_inicial=(
                    _int_sql(
                        linha[
                            "qtd_posicoes_t001"
                        ]
                    )
                    or 0
                ),
                situacao_fisica_inicial=str(
                    linha[
                        "situacao_fisica"
                    ]
                ),
                status_item=STATUS_ITEM_INICIAL,
            )

            inserir_historico_parametrizacao(
                conn,
                id_item_plano=id_item,
                tipo_evento="ITEM_CRIADO",
                usuario=criado_por,
                origem="SISTEMA",
                descricao=(
                    "Item criado no plano de parametrização."
                ),
                status_anterior=None,
                status_novo=STATUS_ITEM_INICIAL,
                referencia_tipo="PLANO_PARAMETRIZACAO",
                referencia_id=id_plano,
            )

            ids_itens.append(
                id_item
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return {
        "id_plano": id_plano,
        "status_plano": STATUS_PLANO_INICIAL,
        "quantidade_materiais": (
            quantidade_materiais
        ),
        "demanda_total_plano": (
            demanda_total_plano
        ),
        "demanda_total_backlog_origem": float(
            demanda_total_backlog_origem
        ),
        "percentual_real_cobertura": (
            percentual_real_cobertura
        ),
        "ids_itens": ids_itens,
    }

def assumir_tarefa(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
) -> dict:
    """
    Assume uma tarefa disponível de um plano ativo.

    A operação é transacional e impede que dois controladores
    assumam o mesmo item.
    """

    controlador_normalizado = controlador.strip()

    if not controlador_normalizado:
        raise ValueError(
            "O controlador é obrigatório."
        )

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        item = obter_item_plano_por_id(
            conn,
            id_item_plano,
        )

        if item is None:
            raise ValueError(
                "Item do plano não encontrado."
            )

        colunas = [
            descricao[0]
            for descricao in conn.execute(
                """
                SELECT
                    i.*,
                    p.status_plano
                FROM plano_parametrizacao_item i
                INNER JOIN plano_parametrizacao p
                    ON p.id = i.id_plano
                WHERE i.id = ?
                """,
                (id_item_plano,),
            ).description
        ]

        dados_item = dict(
            zip(
                colunas,
                item,
            )
        )

        if dados_item["status_plano"] != "ATIVO":
            raise ValueError(
                "A tarefa pertence a um plano que não está ativo."
            )

        if dados_item["status_item"] != "DISPONIVEL":
            raise ValueError(
                "A tarefa não está disponível."
            )

        if dados_item["controlador_responsavel"] is not None:
            raise ValueError(
                "A tarefa já possui controlador responsável."
            )

        assumiu = tentar_assumir_item_plano(
            conn,
            id_item_plano=id_item_plano,
            controlador=controlador_normalizado,
        )

        if not assumiu:
            raise ValueError(
                "A tarefa já foi assumida por outro controlador."
            )

        inserir_historico_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            tipo_evento="TAREFA_ASSUMIDA",
            usuario=controlador_normalizado,
            origem="USUARIO",
            status_anterior="DISPONIVEL",
            status_novo="EM_ANALISE",
            referencia_tipo="ITEM_PLANO",
            referencia_id=id_item_plano,
            descricao="Tarefa assumida pelo controlador.",
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    registro = conn.execute(
        """
        SELECT
            status_item,
            controlador_responsavel,
            assumido_em
        FROM plano_parametrizacao_item
        WHERE id = ?
        """,
        (id_item_plano,),
    ).fetchone()

    return {
        "id_item_plano": id_item_plano,
        "status_item": registro[0],
        "controlador_responsavel": registro[1],
        "assumido_em": registro[2],
    }

def liberar_tarefa(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
) -> dict:
    """
    Libera uma tarefa em análise e devolve o item à fila comum.

    Somente o controlador responsável atual pode liberar a tarefa.
    A operação é transacional.
    """

    controlador_normalizado = controlador.strip()

    if not controlador_normalizado:
        raise ValueError(
            "O controlador é obrigatório."
        )

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        item = obter_item_plano_por_id(
            conn,
            id_item_plano,
        )

        if item is None:
            raise ValueError(
                "Item do plano não encontrado."
            )

        colunas = [
            descricao[0]
            for descricao in conn.execute(
                """
                SELECT
                    i.*,
                    p.status_plano
                FROM plano_parametrizacao_item i
                INNER JOIN plano_parametrizacao p
                    ON p.id = i.id_plano
                WHERE i.id = ?
                """,
                (id_item_plano,),
            ).description
        ]

        dados_item = dict(
            zip(
                colunas,
                item,
            )
        )

        if dados_item["status_plano"] != "ATIVO":
            raise ValueError(
                "A tarefa pertence a um plano que não está ativo."
            )

        if dados_item["status_item"] != "EM_ANALISE":
            raise ValueError(
                "A tarefa não está em análise."
            )

        if (
            dados_item["controlador_responsavel"]
            != controlador_normalizado
        ):
            raise ValueError(
                "A tarefa pertence a outro controlador."
            )

        liberou = tentar_liberar_item_plano(
            conn,
            id_item_plano=id_item_plano,
            controlador=controlador_normalizado,
        )

        if not liberou:
            raise ValueError(
                "A tarefa não pôde ser liberada."
            )

        inserir_historico_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            tipo_evento="TAREFA_LIBERADA",
            usuario=controlador_normalizado,
            origem="USUARIO",
            status_anterior="EM_ANALISE",
            status_novo="DISPONIVEL",
            referencia_tipo="ITEM_PLANO",
            referencia_id=id_item_plano,
            descricao="Tarefa liberada pelo controlador.",
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    registro = conn.execute(
        """
        SELECT
            status_item,
            controlador_responsavel,
            assumido_em
        FROM plano_parametrizacao_item
        WHERE id = ?
        """,
        (id_item_plano,),
    ).fetchone()

    return {
        "id_item_plano": id_item_plano,
        "status_item": registro[0],
        "controlador_responsavel": registro[1],
        "assumido_em": registro[2],
    }

def registrar_decisao(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
    decisao: str,
    min_proposto: float | None = None,
    max_proposto: float | None = None,
    justificativa: str | None = None,
    observacao: str | None = None,
) -> dict:
    """
    Registra a primeira decisão operacional de um item em análise.

    O item deve pertencer a um plano ativo e estar sob
    responsabilidade do controlador informado.
    """

    controlador_normalizado = controlador.strip()

    if not controlador_normalizado:
        raise ValueError(
            "O controlador é obrigatório."
        )

    decisao_normalizada = decisao.strip().upper()

    decisoes_validas = {
        "PARAMETRIZAR",
        "NAO_PARAMETRIZAR",
        "INVESTIGAR",
        "REVISAR_POSTERIORMENTE",
    }

    if decisao_normalizada not in decisoes_validas:
        raise ValueError(
            "Decisão de parametrização inválida."
        )

    justificativa_normalizada = (
        justificativa.strip()
        if justificativa is not None
        else None
    )

    observacao_normalizada = (
        observacao.strip()
        if observacao is not None
        else None
    )

    if decisao_normalizada == "PARAMETRIZAR":
        if min_proposto is None or max_proposto is None:
            raise ValueError(
                "MIN e MAX propostos são obrigatórios "
                "para parametrização."
            )

        min_normalizado = float(min_proposto)
        max_normalizado = float(max_proposto)

        if (
            not math.isfinite(min_normalizado)
            or not math.isfinite(max_normalizado)
        ):
            raise ValueError(
                "MIN e MAX propostos devem ser valores finitos."
            )

        if min_normalizado < 0:
            raise ValueError(
                "O MIN proposto não pode ser negativo."
            )

        if max_normalizado < min_normalizado:
            raise ValueError(
                "O MAX proposto não pode ser menor que o MIN."
            )

        status_novo = "AGUARDANDO_CONFIRMACAO_SAP"

    else:
        if not justificativa_normalizada:
            raise ValueError(
                "A justificativa é obrigatória para esta decisão."
            )

        if min_proposto is not None or max_proposto is not None:
            raise ValueError(
                "MIN e MAX não devem ser informados "
                "para esta decisão."
            )

        min_normalizado = None
        max_normalizado = None

        if decisao_normalizada == "NAO_PARAMETRIZAR":
            status_novo = "ENCERRADO_SEM_PARAMETRIZACAO"
        else:
            status_novo = "EM_ANALISE"

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        item = obter_item_plano_por_id(
            conn,
            id_item_plano,
        )

        if item is None:
            raise ValueError(
                "Item do plano não encontrado."
            )

        cursor_item = conn.execute(
            """
            SELECT
                i.*,
                p.status_plano
            FROM plano_parametrizacao_item i
            INNER JOIN plano_parametrizacao p
                ON p.id = i.id_plano
            WHERE i.id = ?
            """,
            (id_item_plano,),
        )

        colunas = [
            descricao[0]
            for descricao in cursor_item.description
        ]

        dados_item = dict(
            zip(
                colunas,
                item,
            )
        )

        if dados_item["status_plano"] != "ATIVO":
            raise ValueError(
                "A tarefa pertence a um plano que não está ativo."
            )

        if dados_item["status_item"] != "EM_ANALISE":
            raise ValueError(
                "A tarefa não está em análise."
            )

        if (
            dados_item["controlador_responsavel"]
            != controlador_normalizado
        ):
            raise ValueError(
                "A tarefa pertence a outro controlador."
            )

        decisao_ativa = conn.execute(
            """
            SELECT id
            FROM parametrizacao_decisao
            WHERE
                id_item_plano = ?
                AND ativo = 1
            """,
            (id_item_plano,),
        ).fetchone()

        if decisao_ativa is not None:
            raise ValueError(
                "O item já possui uma decisão ativa."
            )

        id_decisao = inserir_decisao_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            numero_revisao=1,
            decisao=decisao_normalizada,
            controlador=controlador_normalizado,
            min_proposto=min_normalizado,
            max_proposto=max_normalizado,
            justificativa=justificativa_normalizada,
            observacao=observacao_normalizada,
        )

        atualizou = atualizar_status_item_apos_decisao(
            conn,
            id_item_plano=id_item_plano,
            controlador=controlador_normalizado,
            status_novo=status_novo,
        )

        if not atualizou:
            raise ValueError(
                "O status da tarefa não pôde ser atualizado."
            )

        inserir_historico_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            tipo_evento="DECISAO_REGISTRADA",
            usuario=controlador_normalizado,
            origem="USUARIO",
            status_anterior="EM_ANALISE",
            status_novo=status_novo,
            referencia_tipo="DECISAO",
            referencia_id=id_decisao,
            descricao=(
                f"Decisão registrada: {decisao_normalizada}."
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    registro = conn.execute(
        """
        SELECT
            status_item,
            controlador_responsavel
        FROM plano_parametrizacao_item
        WHERE id = ?
        """,
        (id_item_plano,),
    ).fetchone()

    return {
        "id_item_plano": id_item_plano,
        "id_decisao": id_decisao,
        "numero_revisao": 1,
        "decisao": decisao_normalizada,
        "status_item": registro[0],
        "controlador_responsavel": registro[1],
    }

def revisar_decisao(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
    decisao: str,
    min_proposto: float | None = None,
    max_proposto: float | None = None,
    justificativa: str | None = None,
    observacao: str | None = None,
) -> dict:
    """
    Revisa uma decisão ativa de um item em análise.

    A decisão anterior é preservada no histórico lógico,
    sendo marcada como inativa. A nova decisão recebe
    numero_revisao incrementado e passa a ser a única ativa.
    """

    controlador_normalizado = controlador.strip()

    if not controlador_normalizado:
        raise ValueError(
            "O controlador é obrigatório."
        )

    decisao_normalizada = decisao.strip().upper()

    decisoes_validas = {
        "PARAMETRIZAR",
        "NAO_PARAMETRIZAR",
        "INVESTIGAR",
        "REVISAR_POSTERIORMENTE",
    }

    if decisao_normalizada not in decisoes_validas:
        raise ValueError(
            "Decisão de parametrização inválida."
        )

    justificativa_normalizada = (
        justificativa.strip()
        if justificativa is not None
        else None
    )

    observacao_normalizada = (
        observacao.strip()
        if observacao is not None
        else None
    )

    if decisao_normalizada == "PARAMETRIZAR":
        if min_proposto is None or max_proposto is None:
            raise ValueError(
                "MIN e MAX propostos são obrigatórios "
                "para parametrização."
            )

        min_normalizado = float(min_proposto)
        max_normalizado = float(max_proposto)

        if (
            not math.isfinite(min_normalizado)
            or not math.isfinite(max_normalizado)
        ):
            raise ValueError(
                "MIN e MAX propostos devem ser valores finitos."
            )

        if min_normalizado < 0:
            raise ValueError(
                "O MIN proposto não pode ser negativo."
            )

        if max_normalizado < min_normalizado:
            raise ValueError(
                "O MAX proposto não pode ser menor que o MIN."
            )

        status_novo = "AGUARDANDO_CONFIRMACAO_SAP"

    else:
        if not justificativa_normalizada:
            raise ValueError(
                "A justificativa é obrigatória para esta decisão."
            )

        if min_proposto is not None or max_proposto is not None:
            raise ValueError(
                "MIN e MAX não devem ser informados "
                "para esta decisão."
            )

        min_normalizado = None
        max_normalizado = None

        if decisao_normalizada == "NAO_PARAMETRIZAR":
            status_novo = "ENCERRADO_SEM_PARAMETRIZACAO"
        else:
            status_novo = "EM_ANALISE"

    try:
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        item = obter_item_plano_por_id(
            conn,
            id_item_plano,
        )

        if item is None:
            raise ValueError(
                "Item do plano não encontrado."
            )

        cursor_item = conn.execute(
            """
            SELECT
                i.*,
                p.status_plano
            FROM plano_parametrizacao_item i
            INNER JOIN plano_parametrizacao p
                ON p.id = i.id_plano
            WHERE i.id = ?
            """,
            (id_item_plano,),
        )

        colunas = [
            descricao[0]
            for descricao in cursor_item.description
        ]

        dados_item = dict(
            zip(
                colunas,
                item,
            )
        )

        if dados_item["status_plano"] != "ATIVO":
            raise ValueError(
                "A tarefa pertence a um plano que não está ativo."
            )

        if dados_item["status_item"] != "EM_ANALISE":
            raise ValueError(
                "A tarefa não está em análise."
            )

        if (
            dados_item["controlador_responsavel"]
            != controlador_normalizado
        ):
            raise ValueError(
                "A tarefa pertence a outro controlador."
            )

        decisao_ativa = obter_decisao_ativa_item(
            conn,
            id_item_plano=id_item_plano,
        )

        if decisao_ativa is None:
            raise ValueError(
                "O item não possui decisão ativa para revisão."
            )

        id_decisao_anterior = int(
            decisao_ativa[0]
        )

        numero_revisao_anterior = int(
            decisao_ativa[1]
        )

        inativou = inativar_decisao_ativa_item(
            conn,
            id_item_plano=id_item_plano,
            id_decisao=id_decisao_anterior,
        )

        if not inativou:
            raise ValueError(
                "A decisão anterior não pôde ser inativada."
            )

        numero_revisao_novo = (
            numero_revisao_anterior + 1
        )

        id_decisao_nova = inserir_decisao_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            numero_revisao=numero_revisao_novo,
            decisao=decisao_normalizada,
            controlador=controlador_normalizado,
            min_proposto=min_normalizado,
            max_proposto=max_normalizado,
            justificativa=justificativa_normalizada,
            observacao=observacao_normalizada,
        )

        atualizou = atualizar_status_item_apos_decisao(
            conn,
            id_item_plano=id_item_plano,
            controlador=controlador_normalizado,
            status_novo=status_novo,
        )

        if not atualizou:
            raise ValueError(
                "O status da tarefa não pôde ser atualizado."
            )

        inserir_historico_parametrizacao(
            conn,
            id_item_plano=id_item_plano,
            tipo_evento="DECISAO_REVISADA",
            usuario=controlador_normalizado,
            origem="USUARIO",
            status_anterior="EM_ANALISE",
            status_novo=status_novo,
            referencia_tipo="DECISAO",
            referencia_id=id_decisao_nova,
            descricao=(
                f"Decisão revisada: {decisao_normalizada}."
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    registro = conn.execute(
        """
        SELECT
            status_item,
            controlador_responsavel
        FROM plano_parametrizacao_item
        WHERE id = ?
        """,
        (id_item_plano,),
    ).fetchone()

    return {
        "id_item_plano": id_item_plano,
        "id_decisao": id_decisao_nova,
        "numero_revisao": numero_revisao_novo,
        "decisao": decisao_normalizada,
        "status_item": registro[0],
        "controlador_responsavel": registro[1],
    }
