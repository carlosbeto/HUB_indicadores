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
