from __future__ import annotations

import sqlite3


# ============================================================
# SCHEMA COMPARTILHADO - ANALISE RESSUPRIMENTO
# ============================================================
#
# Este módulo concentra as definições estruturais compartilhadas
# entre:
#
# - criação de um banco novo;
# - migrations aplicadas a bancos já existentes.
#
# IMPORTANTE:
#
# Este arquivo define estrutura.
# Ele não decide quando uma migration deve ser aplicada,
# não registra versão de migration e não abre conexão com o
# banco.
#
# Essas responsabilidades pertencem aos respectivos
# orquestradores.
# ============================================================


def criar_schema_migrations(conn: sqlite3.Connection) -> None:
    """
    Cria a tabela de controle de versões estruturais do banco.

    A tabela registra migrations efetivamente aplicadas.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,

            nome TEXT NOT NULL UNIQUE,

            aplicado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def criar_plano_parametrizacao(conn: sqlite3.Connection) -> None:
    """
    Cria o cabeçalho dos planos/campanhas de parametrização.

    Cada plano representa um universo congelado em determinado
    momento. Atualizações posteriores de MB51, BINMAT ou estoque
    não alteram retroativamente os indicadores originais do plano.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plano_parametrizacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            nome_plano TEXT NOT NULL,
            onda TEXT,

            data_inicio_demanda TEXT NOT NULL,
            data_fim_demanda TEXT NOT NULL,

            meses_demanda INTEGER NOT NULL
                CHECK (meses_demanda > 0),

            criterio_prioridade TEXT NOT NULL,

            percentual_alvo_demanda REAL
                CHECK (
                    percentual_alvo_demanda IS NULL
                    OR (
                        percentual_alvo_demanda >= 0
                        AND percentual_alvo_demanda <= 100
                    )
                ),

            quantidade_materiais INTEGER NOT NULL
                CHECK (quantidade_materiais >= 0),

            demanda_total_plano REAL NOT NULL
                CHECK (demanda_total_plano >= 0),

            demanda_total_backlog_origem REAL NOT NULL
                CHECK (demanda_total_backlog_origem >= 0),

            percentual_real_cobertura REAL NOT NULL
                CHECK (
                    percentual_real_cobertura >= 0
                    AND percentual_real_cobertura <= 100
                ),

            status_plano TEXT NOT NULL DEFAULT 'RASCUNHO'
                CHECK (
                    status_plano IN (
                        'RASCUNHO',
                        'ATIVO',
                        'CONCLUIDO',
                        'CANCELADO'
                    )
                ),

            criado_por TEXT NOT NULL,

            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            encerrado_em TEXT,

            observacao TEXT
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_parametrizacao_status
        ON plano_parametrizacao(status_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_parametrizacao_periodo
        ON plano_parametrizacao(
            data_inicio_demanda,
            data_fim_demanda
        );
        """
    )


def criar_plano_parametrizacao_item(
    conn: sqlite3.Connection,
) -> None:
    """
    Cria os itens pertencentes a cada plano.

    Esta tabela possui duas responsabilidades:

    1. congelar o snapshot inicial do material/PT02;
    2. manter o estado operacional atual da tarefa.

    Decisões e confirmações SAP permanecem em tabelas históricas
    próprias.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plano_parametrizacao_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            id_plano INTEGER NOT NULL,

            material TEXT NOT NULL,
            posicao_pt02 TEXT NOT NULL,

            descricao_material TEXT,

            prioridade_inicial INTEGER NOT NULL
                CHECK (prioridade_inicial > 0),

            demanda_comercial_inicial REAL NOT NULL DEFAULT 0,
            demanda_tecnica_inicial REAL NOT NULL DEFAULT 0,

            demanda_relevante_inicial REAL NOT NULL DEFAULT 0
                CHECK (demanda_relevante_inicial >= 0),

            pct_demanda_acumulada_inicial REAL
                CHECK (
                    pct_demanda_acumulada_inicial IS NULL
                    OR (
                        pct_demanda_acumulada_inicial >= 0
                        AND pct_demanda_acumulada_inicial <= 100
                    )
                ),

            min_inicial REAL,
            max_inicial REAL,

            saldo_pt02_f5_inicial REAL,
            saldo_pt02_b5_inicial REAL,

            saldo_t001_f5_inicial REAL,
            saldo_t001_b5_inicial REAL,

            qtd_posicoes_t001_inicial INTEGER
                CHECK (
                    qtd_posicoes_t001_inicial IS NULL
                    OR qtd_posicoes_t001_inicial >= 0
                ),

            situacao_fisica_inicial TEXT,

            status_item TEXT NOT NULL DEFAULT 'DISPONIVEL'
                CHECK (
                    status_item IN (
                        'DISPONIVEL',
                        'EM_ANALISE',
                        'AGUARDANDO_CONFIRMACAO_SAP',
                        'CONFIRMADO_SAP',
                        'DIVERGENCIA_SAP',
                        'ENCERRADO_SEM_PARAMETRIZACAO'
                    )
                ),

            controlador_responsavel TEXT,
            assumido_em TEXT,
            analise_concluida_em TEXT,

            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT fk_item_plano
                FOREIGN KEY (id_plano)
                REFERENCES plano_parametrizacao(id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,

            CONSTRAINT fk_item_material
                FOREIGN KEY (material)
                REFERENCES dim_material(material)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,

            CONSTRAINT uq_item_plano_material_posicao
                UNIQUE (
                    id_plano,
                    material,
                    posicao_pt02
                )
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_item_plano
        ON plano_parametrizacao_item(id_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_item_material
        ON plano_parametrizacao_item(material);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_item_status
        ON plano_parametrizacao_item(status_item);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_item_controlador
        ON plano_parametrizacao_item(controlador_responsavel);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_plano_item_fila
        ON plano_parametrizacao_item(
            id_plano,
            status_item,
            prioridade_inicial
        );
        """
    )


def criar_parametrizacao_decisao(
    conn: sqlite3.Connection,
) -> None:
    """
    Cria o histórico de decisões dos controladores.

    Uma nova revisão não sobrescreve a anterior.

    O campo ativo identifica a decisão vigente de cada item.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS parametrizacao_decisao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            id_item_plano INTEGER NOT NULL,

            numero_revisao INTEGER NOT NULL
                CHECK (numero_revisao > 0),

            decisao TEXT NOT NULL
                CHECK (
                    decisao IN (
                        'PARAMETRIZAR',
                        'NAO_PARAMETRIZAR',
                        'INVESTIGAR',
                        'REVISAR_POSTERIORMENTE'
                    )
                ),

            min_proposto REAL,
            max_proposto REAL,

            justificativa TEXT,
            observacao TEXT,

            controlador TEXT NOT NULL,

            decidido_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            alteracao_sap_informada_em TEXT,

            ativo INTEGER NOT NULL DEFAULT 1
                CHECK (ativo IN (0, 1)),

            CONSTRAINT fk_decisao_item
                FOREIGN KEY (id_item_plano)
                REFERENCES plano_parametrizacao_item(id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,

            CONSTRAINT uq_decisao_item_revisao
                UNIQUE (
                    id_item_plano,
                    numero_revisao
                ),

            CONSTRAINT ck_decisao_parametros
                CHECK (
                    (
                        decisao = 'PARAMETRIZAR'
                        AND min_proposto IS NOT NULL
                        AND max_proposto IS NOT NULL
                        AND min_proposto >= 0
                        AND max_proposto >= min_proposto
                    )
                    OR
                    (
                        decisao <> 'PARAMETRIZAR'
                    )
                )
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_decisao_item
        ON parametrizacao_decisao(id_item_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_decisao_tipo
        ON parametrizacao_decisao(decisao);
        """
    )

    # Garante que cada item possua no máximo uma decisão
    # vigente, preservando todas as revisões anteriores.
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_param_decisao_ativa_item
        ON parametrizacao_decisao(id_item_plano)
        WHERE ativo = 1;
        """
    )


def criar_parametrizacao_confirmacao(
    conn: sqlite3.Connection,
) -> None:
    """
    Cria o histórico das verificações realizadas contra BINMAT.

    Uma mesma decisão pode ser verificada várias vezes até que
    seja confirmada ou classificada como divergente.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS parametrizacao_confirmacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            id_decisao INTEGER NOT NULL,

            min_encontrado REAL,
            max_encontrado REAL,

            resultado TEXT NOT NULL
                CHECK (
                    resultado IN (
                        'CONFIRMADO',
                        'DIVERGENTE',
                        'AINDA_NAO_REFLETIDO',
                        'POSICAO_NAO_ENCONTRADA'
                    )
                ),

            arquivo_binmat TEXT,
            hash_binmat TEXT,

            verificado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            observacao TEXT,

            CONSTRAINT fk_confirmacao_decisao
                FOREIGN KEY (id_decisao)
                REFERENCES parametrizacao_decisao(id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_confirmacao_decisao
        ON parametrizacao_confirmacao(id_decisao);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_confirmacao_resultado
        ON parametrizacao_confirmacao(resultado);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_confirmacao_verificado
        ON parametrizacao_confirmacao(verificado_em);
        """
    )


def criar_parametrizacao_historico(
    conn: sqlite3.Connection,
) -> None:
    """
    Cria o histórico de eventos operacionais dos itens.

    O objetivo é permitir reconstruir a trajetória de cada item,
    independentemente do seu estado atual.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS parametrizacao_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            id_item_plano INTEGER NOT NULL,

            tipo_evento TEXT NOT NULL,

            status_anterior TEXT,
            status_novo TEXT,

            usuario TEXT,

            origem TEXT NOT NULL
                CHECK (
                    origem IN (
                        'USUARIO',
                        'ETL',
                        'SISTEMA'
                    )
                ),

            referencia_tipo TEXT,
            referencia_id INTEGER,

            descricao TEXT,

            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT fk_historico_item
                FOREIGN KEY (id_item_plano)
                REFERENCES plano_parametrizacao_item(id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_historico_item
        ON parametrizacao_historico(id_item_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_historico_evento
        ON parametrizacao_historico(tipo_evento);
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_param_historico_data
        ON parametrizacao_historico(criado_em);
        """
    )


def criar_schema_plano_parametrizacao(
    conn: sqlite3.Connection,
) -> None:
    """
    Cria toda a camada estrutural do Plano de Parametrização.

    A ordem é importante por causa das foreign keys:

    plano
        -> item
            -> decisão
                -> confirmação
            -> histórico
    """

    criar_plano_parametrizacao(conn)
    criar_plano_parametrizacao_item(conn)
    criar_parametrizacao_decisao(conn)
    criar_parametrizacao_confirmacao(conn)
    criar_parametrizacao_historico(conn)
