from __future__ import annotations

import sqlite3
from typing import Any


# ============================================================
# PLANO DE PARAMETRIZAÇÃO
# ============================================================

def inserir_plano_parametrizacao(
    conn: sqlite3.Connection,
    *,
    nome_plano: str,
    onda: str,
    data_inicio_demanda: str,
    data_fim_demanda: str,
    meses_demanda: int,
    criterio_prioridade: str,
    percentual_alvo_demanda: float,
    quantidade_materiais: int,
    demanda_total_plano: float,
    demanda_total_backlog_origem: float,
    percentual_real_cobertura: float,
    status_plano: str,
    criado_por: str,
    observacao: str | None = None,
) -> int:
    """
    Insere o cabeçalho de um plano de parametrização.

    A transação é responsabilidade do service chamador.
    Esta função não executa commit.
    """

    cursor = conn.execute(
        """
        INSERT INTO plano_parametrizacao (
            nome_plano,
            onda,
            data_inicio_demanda,
            data_fim_demanda,
            meses_demanda,
            criterio_prioridade,
            percentual_alvo_demanda,
            quantidade_materiais,
            demanda_total_plano,
            demanda_total_backlog_origem,
            percentual_real_cobertura,
            status_plano,
            criado_por,
            observacao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nome_plano,
            onda,
            data_inicio_demanda,
            data_fim_demanda,
            meses_demanda,
            criterio_prioridade,
            percentual_alvo_demanda,
            quantidade_materiais,
            demanda_total_plano,
            demanda_total_backlog_origem,
            percentual_real_cobertura,
            status_plano,
            criado_por,
            observacao,
        ),
    )

    return int(cursor.lastrowid)


# ============================================================
# ITENS DO PLANO
# ============================================================

def inserir_item_plano_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
    material: str,
    posicao_pt02: str,
    descricao_material: str | None,
    prioridade_inicial: int,
    demanda_comercial_inicial: float,
    demanda_tecnica_inicial: float,
    demanda_relevante_inicial: float,
    pct_demanda_acumulada_inicial: float,
    min_inicial: float | None,
    max_inicial: float | None,
    saldo_pt02_f5_inicial: float | None,
    saldo_pt02_b5_inicial: float | None,
    saldo_t001_f5_inicial: float,
    saldo_t001_b5_inicial: float,
    qtd_posicoes_t001_inicial: int,
    situacao_fisica_inicial: str,
    status_item: str,
) -> int:
    """
    Insere o snapshot inicial de um material dentro do plano.

    Os valores representam o estado existente no momento
    da criação da onda e não devem ser atualizados por
    cargas posteriores de MB51, BINMAT ou VISAO_GERAL.

    A transação é responsabilidade do service chamador.
    """

    cursor = conn.execute(
        """
        INSERT INTO plano_parametrizacao_item (
            id_plano,
            material,
            posicao_pt02,
            descricao_material,
            prioridade_inicial,
            demanda_comercial_inicial,
            demanda_tecnica_inicial,
            demanda_relevante_inicial,
            pct_demanda_acumulada_inicial,
            min_inicial,
            max_inicial,
            saldo_pt02_f5_inicial,
            saldo_pt02_b5_inicial,
            saldo_t001_f5_inicial,
            saldo_t001_b5_inicial,
            qtd_posicoes_t001_inicial,
            situacao_fisica_inicial,
            status_item
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id_plano,
            material,
            posicao_pt02,
            descricao_material,
            prioridade_inicial,
            demanda_comercial_inicial,
            demanda_tecnica_inicial,
            demanda_relevante_inicial,
            pct_demanda_acumulada_inicial,
            min_inicial,
            max_inicial,
            saldo_pt02_f5_inicial,
            saldo_pt02_b5_inicial,
            saldo_t001_f5_inicial,
            saldo_t001_b5_inicial,
            qtd_posicoes_t001_inicial,
            situacao_fisica_inicial,
            status_item,
        ),
    )

    return int(cursor.lastrowid)


# ============================================================
# HISTÓRICO / AUDITORIA
# ============================================================

def inserir_historico_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    tipo_evento: str,
    usuario: str,
    origem: str,
    descricao: str,
    status_anterior: str | None = None,
    status_novo: str | None = None,
    referencia_tipo: str | None = None,
    referencia_id: int | None = None,
) -> int:
    """
    Registra um evento auditável relacionado ao item do plano.

    O histórico é append-only: eventos anteriores não devem
    ser sobrescritos.

    A transação é responsabilidade do service chamador.
    """

    cursor = conn.execute(
        """
        INSERT INTO parametrizacao_historico (
            id_item_plano,
            tipo_evento,
            status_anterior,
            status_novo,
            usuario,
            origem,
            referencia_tipo,
            referencia_id,
            descricao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id_item_plano,
            tipo_evento,
            status_anterior,
            status_novo,
            usuario,
            origem,
            referencia_tipo,
            referencia_id,
            descricao,
        ),
    )

    return int(cursor.lastrowid)


# ============================================================
# CONSULTAS DE APOIO
# ============================================================

def obter_plano_por_id(
    conn: sqlite3.Connection,
    id_plano: int,
) -> sqlite3.Row | None:
    """
    Retorna um plano pelo identificador.
    """

    return conn.execute(
        """
        SELECT *
        FROM plano_parametrizacao
        WHERE id = ?
        """,
        (id_plano,),
    ).fetchone()

def obter_resumo_operacional_plano(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
) -> dict[str, Any] | None:
    """
    Retorna o resumo operacional do plano com contrato explícito.
    """

    cursor = conn.execute(
        """
        SELECT
            id AS id_plano,
            nome_plano AS nome,
            onda,
            status_plano AS status
        FROM plano_parametrizacao
        WHERE id = ?
        """,
        (id_plano,),
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


def tentar_ativar_plano_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
    ativado_por: str,
) -> bool:
    """Ativa atomicamente um plano que ainda esteja em rascunho.

    O estado ``RASCUNHO`` faz parte do próprio ``WHERE`` para proteger a
    transição contra duas tentativas simultâneas. O repository não executa
    commit: a transação pertence ao service, que reúne todas as validações.
    """

    cursor = conn.execute(
        """
        UPDATE plano_parametrizacao
        SET
            status_plano = 'ATIVO',
            ativado_por = ?,
            ativado_em = CURRENT_TIMESTAMP
        WHERE
            id = ?
            AND status_plano = 'RASCUNHO'
        """,
        (
            ativado_por,
            id_plano,
        ),
    )

    return cursor.rowcount == 1


def obter_ativacao_plano(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
) -> dict[str, Any] | None:
    """Retorna o estado e os dados de ativação com contrato explícito."""

    cursor = conn.execute(
        """
        SELECT
            id AS id_plano,
            status_plano AS status,
            ativado_por,
            ativado_em
        FROM plano_parametrizacao
        WHERE id = ?
        """,
        (id_plano,),
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

def contar_itens_plano(
    conn: sqlite3.Connection,
    id_plano: int,
) -> int:
    """
    Retorna a quantidade de itens pertencentes ao plano.
    """

    resultado = conn.execute(
        """
        SELECT COUNT(*)
        FROM plano_parametrizacao_item
        WHERE id_plano = ?
        """,
        (id_plano,),
    ).fetchone()

    return int(resultado[0])


def contar_historicos_plano(
    conn: sqlite3.Connection,
    id_plano: int,
) -> int:
    """
    Retorna a quantidade de eventos de histórico associados
    aos itens de determinado plano.
    """

    resultado = conn.execute(
        """
        SELECT COUNT(*)
        FROM parametrizacao_historico h
        INNER JOIN plano_parametrizacao_item i
            ON i.id = h.id_item_plano
        WHERE i.id_plano = ?
        """,
        (id_plano,),
    ).fetchone()

    return int(resultado[0])


def listar_itens_plano(
    conn: sqlite3.Connection,
    id_plano: int,
) -> list[Any]:
    """
    Retorna os itens do plano na prioridade original.

    Esta consulta será útil tanto para auditoria quanto
    para o futuro drill-down dos indicadores da aplicação.
    """

    return conn.execute(
        """
        SELECT *
        FROM plano_parametrizacao_item
        WHERE id_plano = ?
        ORDER BY prioridade_inicial, material, posicao_pt02
        """,
        (id_plano,),
    ).fetchall()

def listar_fila_operacional_plano(
    conn: sqlite3.Connection,
    *,
    id_plano: int,
) -> list[dict[str, Any]]:
    """
    Retorna a fila operacional do plano com contrato explícito.

    A fila usa apenas dados persistidos do snapshot e do workflow.
    Não consulta o estado atual do BINMAT.
    """

    cursor = conn.execute(
        """
        SELECT
            id AS id_item_plano,
            material,
            descricao_material,
            posicao_pt02,
            prioridade_inicial AS prioridade,
            demanda_relevante_inicial AS demanda_relevante,
            pct_demanda_acumulada_inicial AS pct_demanda_acumulada,
            status_item AS status,
            controlador_responsavel,
            assumido_em
        FROM plano_parametrizacao_item
        WHERE id_plano = ?
        ORDER BY
            prioridade_inicial,
            material,
            posicao_pt02
        """,
        (id_plano,),
    )

    colunas = [
        descricao[0]
        for descricao in cursor.description
    ]

    return [
        dict(
            zip(
                colunas,
                registro,
            )
        )
        for registro in cursor.fetchall()
    ]

def obter_item_plano_por_id(
    conn: sqlite3.Connection,
    id_item_plano: int,
) -> sqlite3.Row | tuple | None:
    """
    Retorna um item do plano junto com o status do plano pai.
    """

    return conn.execute(
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
    ).fetchone()


def tentar_assumir_item_plano(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
) -> bool:
    """
    Tenta assumir atomicamente um item disponível.

    Retorna True somente se exatamente um registro for alterado.
    Não executa commit.
    """

    cursor = conn.execute(
        """
        UPDATE plano_parametrizacao_item
        SET
            status_item = 'EM_ANALISE',
            controlador_responsavel = ?,
            assumido_em = CURRENT_TIMESTAMP,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE
            id = ?
            AND status_item = 'DISPONIVEL'
            AND controlador_responsavel IS NULL
        """,
        (
            controlador,
            id_item_plano,
        ),
    )

    return cursor.rowcount == 1


def tentar_liberar_item_plano(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
) -> bool:
    """
    Tenta liberar atomicamente uma tarefa em análise.

    A liberação só ocorre quando:
    - o item está EM_ANALISE;
    - o controlador informado é o responsável atual.

    Não executa commit.
    """

    cursor = conn.execute(
        """
        UPDATE plano_parametrizacao_item
        SET
            status_item = 'DISPONIVEL',
            controlador_responsavel = NULL,
            assumido_em = NULL,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE
            id = ?
            AND status_item = 'EM_ANALISE'
            AND controlador_responsavel = ?
        """,
        (
            id_item_plano,
            controlador,
        ),
    )

    return cursor.rowcount == 1

def inserir_decisao_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    numero_revisao: int,
    decisao: str,
    controlador: str,
    min_proposto: float | None = None,
    max_proposto: float | None = None,
    justificativa: str | None = None,
    observacao: str | None = None,
) -> int:
    """
    Registra uma decisão de parametrização para o item.

    A transação é responsabilidade do service chamador.
    """

    cursor = conn.execute(
        """
        INSERT INTO parametrizacao_decisao (
            id_item_plano,
            numero_revisao,
            decisao,
            min_proposto,
            max_proposto,
            justificativa,
            observacao,
            controlador,
            ativo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            id_item_plano,
            numero_revisao,
            decisao,
            min_proposto,
            max_proposto,
            justificativa,
            observacao,
            controlador,
        ),
    )

    return int(cursor.lastrowid)


def atualizar_status_item_apos_decisao(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    controlador: str,
    status_novo: str,
) -> bool:
    """
    Atualiza atomicamente o status de um item em análise.

    Somente o controlador responsável atual pode alterar o item.
    A transação é responsabilidade do service chamador.
    """

    cursor = conn.execute(
        """
        UPDATE plano_parametrizacao_item
        SET
            status_item = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE
            id = ?
            AND status_item = 'EM_ANALISE'
            AND controlador_responsavel = ?
        """,
        (
            status_novo,
            id_item_plano,
            controlador,
        ),
    )

    return cursor.rowcount == 1

def obter_decisao_ativa_item(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
) -> sqlite3.Row | tuple | None:
    """
    Retorna a decisão ativa atual do item, se existir.
    """

    return conn.execute(
        """
        SELECT
            id,
            numero_revisao,
            decisao,
            min_proposto,
            max_proposto,
            justificativa,
            observacao,
            controlador,
            decidido_em,
            alteracao_sap_informada_em,
            ativo
        FROM parametrizacao_decisao
        WHERE
            id_item_plano = ?
            AND ativo = 1
        """,
        (id_item_plano,),
    ).fetchone()


def inativar_decisao_ativa_item(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    id_decisao: int,
) -> bool:
    """
    Inativa atomicamente a decisão ativa atual do item.

    A transação é responsabilidade do service chamador.
    """

    cursor = conn.execute(
        """
        UPDATE parametrizacao_decisao
        SET ativo = 0
        WHERE
            id = ?
            AND id_item_plano = ?
            AND ativo = 1
        """,
        (
            id_decisao,
            id_item_plano,
        ),
    )

    return cursor.rowcount == 1


def obter_posicao_binmat_atual(
    conn: sqlite3.Connection,
    *,
    material: str,
    posicao: str,
) -> tuple | None:
    """
    Retorna o MIN/MAX atual da posição somente quando ela
    está presente no snapshot BINMAT atual.
    """

    return conn.execute(
        """
        SELECT
            p.quantidade_minima,
            p.quantidade_maxima,
            f.arquivo_origem
        FROM dim_posicao_material AS p

        INNER JOIN posicao_material_fontes AS f
            ON f.id_posicao_material = p.id
           AND f.fonte = 'BINMAT'
           AND f.presente_atual = 1

        WHERE
            p.material = ?
            AND p.posicao = ?
        """,
        (
            material,
            posicao,
        ),
    ).fetchone()


def inserir_confirmacao_parametrizacao(
    conn: sqlite3.Connection,
    *,
    id_decisao: int,
    resultado: str,
    min_encontrado: float | None = None,
    max_encontrado: float | None = None,
    arquivo_binmat: str | None = None,
    hash_binmat: str | None = None,
    observacao: str | None = None,
) -> int:
    """
    Registra uma verificação da parametrização no BINMAT.

    Uma mesma decisão pode possuir várias verificações ao longo
    do tempo. A transação é responsabilidade do service.
    """

    cursor = conn.execute(
        """
        INSERT INTO parametrizacao_confirmacao (
            id_decisao,
            min_encontrado,
            max_encontrado,
            resultado,
            arquivo_binmat,
            hash_binmat,
            observacao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id_decisao,
            min_encontrado,
            max_encontrado,
            resultado,
            arquivo_binmat,
            hash_binmat,
            observacao,
        ),
    )

    return int(cursor.lastrowid)


def atualizar_status_item_confirmacao_sap(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
    status_novo: str,
) -> bool:
    """
    Atualiza o status do item durante a verificação SAP.

    A operação só é permitida enquanto o item estiver aguardando
    confirmação SAP.
    """

    cursor = conn.execute(
        """
        UPDATE plano_parametrizacao_item
        SET
            status_item = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE
            id = ?
            AND status_item = 'AGUARDANDO_CONFIRMACAO_SAP'
        """,
        (
            status_novo,
            id_item_plano,
        ),
    )

    return cursor.rowcount == 1

def obter_detalhe_operacional_item_base(
    conn: sqlite3.Connection,
    *,
    id_item_plano: int,
) -> dict[str, Any] | None:
    """
    Retorna os dados estruturais de um item do plano junto com
    o cabeçalho do plano.

    Esta consulta representa o snapshot persistido da onda e o
    estado atual do workflow do item. Não consulta o BINMAT atual.
    """

    cursor = conn.execute(
        """
        SELECT
            p.id AS id_plano,
            p.nome_plano,
            p.onda,
            p.status_plano,

            i.id AS id_item_plano,
            i.material,
            i.descricao_material,
            i.posicao_pt02,
            i.prioridade_inicial,
            i.status_item,
            i.controlador_responsavel,
            i.assumido_em,

            i.demanda_comercial_inicial,
            i.demanda_tecnica_inicial,
            i.demanda_relevante_inicial,
            i.pct_demanda_acumulada_inicial,

            i.min_inicial,
            i.max_inicial,

            i.saldo_pt02_f5_inicial,
            i.saldo_pt02_b5_inicial,
            i.saldo_t001_f5_inicial,
            i.saldo_t001_b5_inicial,
            i.qtd_posicoes_t001_inicial,
            i.situacao_fisica_inicial

        FROM plano_parametrizacao_item AS i

        INNER JOIN plano_parametrizacao AS p
            ON p.id = i.id_plano

        WHERE i.id = ?
        """,
        (id_item_plano,),
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


def obter_ultima_confirmacao_decisao(
    conn: sqlite3.Connection,
    *,
    id_decisao: int,
) -> tuple | None:
    """
    Retorna a confirmação SAP mais recente de uma decisão.

    Uma mesma decisão pode possuir várias verificações.
    O maior ID representa a última confirmação persistida.
    """

    return conn.execute(
        """
        SELECT
            id,
            id_decisao,
            min_encontrado,
            max_encontrado,
            resultado,
            arquivo_binmat,
            hash_binmat,
            verificado_em,
            observacao
        FROM parametrizacao_confirmacao
        WHERE id_decisao = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (id_decisao,),
    ).fetchone()
