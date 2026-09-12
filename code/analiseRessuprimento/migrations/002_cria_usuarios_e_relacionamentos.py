from __future__ import annotations

"""
Migration 002 - usuários e relacionamentos humanos do workflow.

Esta migration é executada depois da migration 001. Ela introduz o
cadastro de usuários e transforma os campos de matrícula já existentes
em relacionamentos explícitos no modelo E/R.

O SQLite não permite acrescentar uma FOREIGN KEY a uma coluna existente
com um simples ALTER TABLE. Por isso, as cinco tabelas do workflow são
reconstruídas dentro de uma única transação:

1. as tabelas atuais recebem nomes temporários;
2. as novas tabelas são criadas com as FKs desejadas;
3. todos os dados anteriores são copiados preservando seus IDs;
4. a integridade referencial é verificada;
5. as tabelas temporárias são removidas;
6. a versão 002 é registrada somente ao final.

Se qualquer etapa falhar, o rollback devolve o banco ao estado anterior.
"""

import sqlite3
from pathlib import Path


MIGRATION_VERSION = 2
MIGRATION_NAME = "002_cria_usuarios_e_relacionamentos"

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"


TABELAS_WORKFLOW = (
    "plano_parametrizacao",
    "plano_parametrizacao_item",
    "parametrizacao_decisao",
    "parametrizacao_confirmacao",
    "parametrizacao_historico",
)


def _tabela_existe(
    conn: sqlite3.Connection,
    nome_tabela: str,
) -> bool:
    """Verifica no catálogo do SQLite se uma tabela está presente."""

    registro = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1;
        """,
        (nome_tabela,),
    ).fetchone()

    return registro is not None


def _migration_registrada(
    conn: sqlite3.Connection,
    version: int,
) -> bool:
    """Consulta se determinada versão já foi aplicada ao banco."""

    registro = conn.execute(
        """
        SELECT 1
        FROM schema_migrations
        WHERE version = ?
        LIMIT 1;
        """,
        (version,),
    ).fetchone()

    return registro is not None


def _validar_estado_inicial(conn: sqlite3.Connection) -> None:
    """
    Garante que o banco está exatamente no estado aceito pela migration.

    A validação evita continuar diante de schema parcial, versão 001
    ausente ou resíduos de uma intervenção manual anterior.
    """

    if not _tabela_existe(conn, "schema_migrations"):
        raise RuntimeError(
            "A tabela schema_migrations não foi encontrada."
        )

    if not _migration_registrada(conn, 1):
        raise RuntimeError(
            "A migration 001 deve estar aplicada antes da migration 002."
        )

    tabelas_ausentes = [
        tabela
        for tabela in TABELAS_WORKFLOW
        if not _tabela_existe(conn, tabela)
    ]

    if tabelas_ausentes:
        raise RuntimeError(
            "Tabelas obrigatórias ausentes antes da migration 002: "
            + ", ".join(tabelas_ausentes)
        )

    if _tabela_existe(conn, "usuarios"):
        raise RuntimeError(
            "A tabela usuarios já existe sem a migration 002 registrada."
        )

    tabelas_temporarias = [
        f"_migration_002_{tabela}"
        for tabela in TABELAS_WORKFLOW
    ]

    existentes = [
        tabela
        for tabela in tabelas_temporarias
        if _tabela_existe(conn, tabela)
    ]

    if existentes:
        raise RuntimeError(
            "Foram encontradas tabelas temporárias da migration 002: "
            + ", ".join(existentes)
        )


def _renomear_tabelas_anteriores(
    conn: sqlite3.Connection,
) -> None:
    """
    Reserva as tabelas atuais para permitir sua reconstrução segura.

    A ordem inversa começa pelas tabelas-filhas. Os índices antigos são
    removidos depois da renomeação porque o nome de um índice é global
    no banco; mantê-los impediria a criação dos novos índices.
    """

    for tabela in reversed(TABELAS_WORKFLOW):
        conn.execute(
            f"ALTER TABLE {tabela} "
            f"RENAME TO _migration_002_{tabela};"
        )

    indices_anteriores = (
        "idx_plano_parametrizacao_status",
        "idx_plano_parametrizacao_periodo",
        "idx_plano_item_plano",
        "idx_plano_item_material",
        "idx_plano_item_status",
        "idx_plano_item_controlador",
        "idx_plano_item_fila",
        "idx_param_decisao_item",
        "idx_param_decisao_tipo",
        "uq_param_decisao_ativa_item",
        "idx_param_confirmacao_decisao",
        "idx_param_confirmacao_resultado",
        "idx_param_confirmacao_verificado",
        "idx_param_historico_item",
        "idx_param_historico_evento",
        "idx_param_historico_data",
    )

    for indice in indices_anteriores:
        conn.execute(
            f"DROP INDEX {indice};"
        )


def _criar_usuarios(conn: sqlite3.Connection) -> None:
    """
    Cria o cadastro de usuários humanos do Ressuprimento.

    A matrícula é única e obedece ao padrão corporativo de duas letras
    maiúsculas seguidas de seis números. A desativação preserva o usuário
    para auditoria, usando SIM/NAO em vez de exclusão física.
    """

    conn.execute(
        """
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            matricula TEXT NOT NULL UNIQUE
                CHECK (
                    matricula GLOB
                    '[A-Z][A-Z][0-9][0-9][0-9][0-9][0-9][0-9]'
                ),

            nome TEXT NOT NULL
                CHECK (TRIM(nome) <> ''),

            ativo TEXT NOT NULL DEFAULT 'SIM'
                CHECK (ativo IN ('SIM', 'NAO')),

            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_usuarios_ativo
        ON usuarios(ativo);
        """
    )


def _criar_plano_parametrizacao(
    conn: sqlite3.Connection,
) -> None:
    """
    Recria o cabeçalho dos planos incluindo a auditoria de ativação.

    criado_por continua textual porque o plano pode nascer por SISTEMA.
    ativado_por representa uma ação humana e, por isso, referencia uma
    matrícula cadastrada em usuarios.
    """

    conn.execute(
        """
        CREATE TABLE plano_parametrizacao (
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
            ativado_por TEXT,
            ativado_em TEXT,
            encerrado_em TEXT,

            observacao TEXT,

            CONSTRAINT fk_plano_usuario_ativacao
                FOREIGN KEY (ativado_por)
                REFERENCES usuarios(matricula)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_parametrizacao_status
        ON plano_parametrizacao(status_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_parametrizacao_periodo
        ON plano_parametrizacao(
            data_inicio_demanda,
            data_fim_demanda
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_parametrizacao_ativado_por
        ON plano_parametrizacao(ativado_por);
        """
    )


def _criar_plano_parametrizacao_item(
    conn: sqlite3.Connection,
) -> None:
    """
    Recria os itens preservando snapshot e estado operacional.

    controlador_responsavel passa a ser uma FK para usuarios.matricula.
    O campo permanece nulo enquanto a tarefa estiver disponível.
    """

    conn.execute(
        """
        CREATE TABLE plano_parametrizacao_item (
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

            CONSTRAINT fk_item_controlador
                FOREIGN KEY (controlador_responsavel)
                REFERENCES usuarios(matricula)
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
        CREATE INDEX idx_plano_item_plano
        ON plano_parametrizacao_item(id_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_item_material
        ON plano_parametrizacao_item(material);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_item_status
        ON plano_parametrizacao_item(status_item);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_item_controlador
        ON plano_parametrizacao_item(controlador_responsavel);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_plano_item_fila
        ON plano_parametrizacao_item(
            id_plano,
            status_item,
            prioridade_inicial
        );
        """
    )


def _criar_parametrizacao_decisao(
    conn: sqlite3.Connection,
) -> None:
    """
    Recria as decisões vinculando o controlador a um usuário válido.

    Permanecem intactas as regras de revisão, MIN/MAX e decisão ativa.
    """

    conn.execute(
        """
        CREATE TABLE parametrizacao_decisao (
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

            CONSTRAINT fk_decisao_controlador
                FOREIGN KEY (controlador)
                REFERENCES usuarios(matricula)
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
        CREATE INDEX idx_param_decisao_item
        ON parametrizacao_decisao(id_item_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_decisao_tipo
        ON parametrizacao_decisao(decisao);
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX uq_param_decisao_ativa_item
        ON parametrizacao_decisao(id_item_plano)
        WHERE ativo = 1;
        """
    )


def _criar_parametrizacao_confirmacao(
    conn: sqlite3.Connection,
) -> None:
    """
    Recria as confirmações SAP sem alterar seu contrato de negócio.

    Esta tabela precisa ser reconstruída porque depende da tabela de
    decisões, que também é reconstruída nesta migration.
    """

    conn.execute(
        """
        CREATE TABLE parametrizacao_confirmacao (
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
        CREATE INDEX idx_param_confirmacao_decisao
        ON parametrizacao_confirmacao(id_decisao);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_confirmacao_resultado
        ON parametrizacao_confirmacao(resultado);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_confirmacao_verificado
        ON parametrizacao_confirmacao(verificado_em);
        """
    )


def _criar_parametrizacao_historico(
    conn: sqlite3.Connection,
) -> None:
    """
    Recria o histórico mantendo atores técnicos e usuários humanos.

    usuario continua sendo o ator legível e pode conter SISTEMA ou ETL.
    usuario_matricula é preenchido somente em ações humanas e cria o
    relacionamento opcional com usuarios.
    """

    conn.execute(
        """
        CREATE TABLE parametrizacao_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            id_item_plano INTEGER NOT NULL,

            tipo_evento TEXT NOT NULL,

            status_anterior TEXT,
            status_novo TEXT,

            usuario TEXT,
            usuario_matricula TEXT,

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
                ON DELETE RESTRICT,

            CONSTRAINT fk_historico_usuario
                FOREIGN KEY (usuario_matricula)
                REFERENCES usuarios(matricula)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_historico_item
        ON parametrizacao_historico(id_item_plano);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_historico_evento
        ON parametrizacao_historico(tipo_evento);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_historico_data
        ON parametrizacao_historico(criado_em);
        """
    )

    conn.execute(
        """
        CREATE INDEX idx_param_historico_usuario
        ON parametrizacao_historico(usuario_matricula);
        """
    )


def _copiar_dados(conn: sqlite3.Connection) -> None:
    """
    Copia integralmente o conteúdo legado para as tabelas novas.

    Os IDs e timestamps são informados explicitamente para preservar a
    identidade dos registros e todos os relacionamentos já existentes.
    Os novos campos permanecem NULL nos eventos anteriores à migration.
    """

    conn.execute(
        """
        INSERT INTO plano_parametrizacao (
            id,
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
            criado_em,
            encerrado_em,
            observacao
        )
        SELECT
            id,
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
            criado_em,
            encerrado_em,
            observacao
        FROM _migration_002_plano_parametrizacao;
        """
    )

    conn.execute(
        """
        INSERT INTO plano_parametrizacao_item (
            id,
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
            controlador_responsavel,
            assumido_em,
            analise_concluida_em,
            criado_em,
            atualizado_em
        )
        SELECT
            id,
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
            controlador_responsavel,
            assumido_em,
            analise_concluida_em,
            criado_em,
            atualizado_em
        FROM _migration_002_plano_parametrizacao_item;
        """
    )

    conn.execute(
        """
        INSERT INTO parametrizacao_decisao (
            id,
            id_item_plano,
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
        )
        SELECT
            id,
            id_item_plano,
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
        FROM _migration_002_parametrizacao_decisao;
        """
    )

    conn.execute(
        """
        INSERT INTO parametrizacao_confirmacao (
            id,
            id_decisao,
            min_encontrado,
            max_encontrado,
            resultado,
            arquivo_binmat,
            hash_binmat,
            verificado_em,
            observacao
        )
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
        FROM _migration_002_parametrizacao_confirmacao;
        """
    )

    conn.execute(
        """
        INSERT INTO parametrizacao_historico (
            id,
            id_item_plano,
            tipo_evento,
            status_anterior,
            status_novo,
            usuario,
            origem,
            referencia_tipo,
            referencia_id,
            descricao,
            criado_em
        )
        SELECT
            id,
            id_item_plano,
            tipo_evento,
            status_anterior,
            status_novo,
            usuario,
            origem,
            referencia_tipo,
            referencia_id,
            descricao,
            criado_em
        FROM _migration_002_parametrizacao_historico;
        """
    )


def _remover_tabelas_anteriores(
    conn: sqlite3.Connection,
) -> None:
    """Remove as cópias temporárias começando pelas tabelas-filhas."""

    ordem_remocao = (
        "parametrizacao_confirmacao",
        "parametrizacao_historico",
        "parametrizacao_decisao",
        "plano_parametrizacao_item",
        "plano_parametrizacao",
    )

    for tabela in ordem_remocao:
        conn.execute(
            f"DROP TABLE _migration_002_{tabela};"
        )


def _registrar_migration(conn: sqlite3.Connection) -> None:
    """Registra a versão 002 dentro da mesma transação do schema."""

    conn.execute(
        """
        INSERT INTO schema_migrations (version, nome)
        VALUES (?, ?);
        """,
        (
            MIGRATION_VERSION,
            MIGRATION_NAME,
        ),
    )


def aplicar_migration(
    db_path: Path | str | None = None,
) -> None:
    """
    Aplica a migration 002 de forma atômica e repetível.

    foreign_keys é desligado somente durante a reconstrução das tabelas,
    como exige o procedimento de alteração estrutural do SQLite. Antes e
    depois da cópia, foreign_key_check protege a integridade do modelo.
    Uma segunda execução apenas informa que a versão já foi aplicada.
    """

    banco = Path(db_path) if db_path is not None else DB_PATH

    if not banco.exists():
        raise FileNotFoundError(
            "Banco SQLite não encontrado. "
            f"Caminho esperado: {banco}"
        )

    conn = sqlite3.connect(banco)

    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        if _migration_registrada(conn, MIGRATION_VERSION):
            print(
                f"Migration {MIGRATION_VERSION:03d} "
                "já está registrada no banco."
            )
            print("Nenhuma alteração foi realizada.")
            return

        _validar_estado_inicial(conn)

        erros_antes = conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        if erros_antes:
            raise RuntimeError(
                "O banco possui violações de foreign key "
                "antes da migration 002."
            )

        # O PRAGMA precisa ser alterado antes de BEGIN. Dentro de uma
        # transação o SQLite ignora a tentativa de mudar foreign_keys.
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("BEGIN IMMEDIATE;")

        _renomear_tabelas_anteriores(conn)

        _criar_usuarios(conn)
        _criar_plano_parametrizacao(conn)
        _criar_plano_parametrizacao_item(conn)
        _criar_parametrizacao_decisao(conn)
        _criar_parametrizacao_confirmacao(conn)
        _criar_parametrizacao_historico(conn)

        _copiar_dados(conn)
        _remover_tabelas_anteriores(conn)

        # Mesmo com a fiscalização temporariamente desligada, o comando
        # abaixo audita todas as relações antes de autorizar o commit.
        erros_depois = conn.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        if erros_depois:
            raise RuntimeError(
                "A migration 002 produziu violações de foreign key."
            )

        _registrar_migration(conn)
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


if __name__ == "__main__":
    aplicar_migration()
