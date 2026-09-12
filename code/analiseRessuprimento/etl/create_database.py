from pathlib import Path
import sqlite3
import importlib.util
from contextlib import closing

# ============================================================
# CAMINHOS DO MÓDULO
# ============================================================
#
# O script está em:
#
# code\analiseRessuprimento\etl\create_database.py
#
# Usamos caminhos relativos ao próprio módulo para que o mesmo
# código funcione posteriormente tanto em DEV quanto em PROD.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_DIR = BASE_DIR / "data_db"
DB_PATH = DB_DIR / "ressuprimento.sqlite"


def carregar_migration_001():
    """
    Carrega a migration 001 diretamente pelo caminho do arquivo.

    O prefixo numérico do nome do arquivo impede importação
    Python convencional, então usamos importlib.
    """

    migration_path = (
        BASE_DIR
        / "migrations"
        / "001_cria_plano_parametrizacao.py"
    )

    if not migration_path.exists():
        raise FileNotFoundError(
            "Migration 001 não encontrada. "
            f"Caminho esperado: {migration_path}"
        )

    spec = importlib.util.spec_from_file_location(
        "migration_001_cria_plano_parametrizacao",
        migration_path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Não foi possível carregar a migration 001."
        )

    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    return modulo


def carregar_migration_002():
    """
    Carrega a migration 002 diretamente pelo caminho do arquivo.

    O prefixo numérico do nome do arquivo impede importação
    Python convencional, então usamos importlib.
    """

    migration_path = (
        BASE_DIR
        / "migrations"
        / "002_cria_usuarios_e_relacionamentos.py"
    )

    if not migration_path.exists():
        raise FileNotFoundError(
            "Migration 002 não encontrada. "
            f"Caminho esperado: {migration_path}"
        )

    spec = importlib.util.spec_from_file_location(
        "migration_002_cria_usuarios_e_relacionamentos",
        migration_path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Não foi possível carregar a migration 002."
        )

    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    return modulo


def criar_banco(
    db_path: Path | None = None,
) -> None:
    """
    Cria o banco SQLite do módulo analiseRessuprimento.

    Princípios do modelo:

    1. Material é uma entidade central.
    2. Um material pode possuir muitos movimentos MB51.
    3. Um material pode estar associado a várias posições.
    4. Não existe restrição estrutural a PT02 ou T001.
       Outros tipos de depósito poderão ser incorporados.
    5. Os relacionamentos são declarados com FOREIGN KEY
       para permitir integridade referencial e visualização
       adequada do modelo E/R no DBeaver.
    """

    banco = db_path if db_path is not None else DB_PATH
    banco.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("CRIANDO BANCO - ANALISE RESSUPRIMENTO")
    print("=" * 70)
    print(f"Banco: {banco}")
    print()

    with closing(sqlite3.connect(banco)) as conn:

        # SQLite exige ativação explícita das foreign keys
        # em cada conexão.
        conn.execute("PRAGMA foreign_keys = ON;")

        cursor = conn.cursor()

        # ====================================================
        # 1. DIMENSÃO DE MATERIAIS
        # ====================================================
        #
        # Material é a entidade central do modelo.
        #
        # MB51, BINMAT e Visão Geral poderão fornecer
        # informações sobre o mesmo material.
        #
        # O código SAP do material é usado como PK porque é
        # a identificação natural dessa entidade no processo.
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dim_material (
                material TEXT PRIMARY KEY,

                descricao_material TEXT,

                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # ====================================================
        # 2. MOVIMENTAÇÕES MB51
        # ====================================================
        #
        # Uma linha representa um movimento SAP.
        #
        # Relação:
        #
        # dim_material 1 ---- N fact_mb51_movimentos
        #
        # A combinação:
        #
        # documento_material + item_documento
        #
        # foi validada na MB51 atual:
        #
        # - 247.173 linhas
        # - 0 duplicidades
        # - 0 chaves nulas
        #
        # Portanto ela será nossa chave natural de proteção
        # contra cargas duplicadas.
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fact_mb51_movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                material TEXT NOT NULL,

                data_lancamento TEXT NOT NULL,

                tipo_movimento TEXT NOT NULL,
                debito_credito TEXT,

                quantidade REAL NOT NULL,

                documento_material TEXT NOT NULL,
                item_documento TEXT NOT NULL,

                deposito TEXT,
                centro_custo TEXT,
                usuario TEXT,

                arquivo_origem TEXT NOT NULL,
                carregado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT uq_mb51_documento_item
                    UNIQUE (documento_material, item_documento),

                CONSTRAINT fk_mb51_material
                    FOREIGN KEY (material)
                    REFERENCES dim_material(material)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mb51_material
            ON fact_mb51_movimentos(material);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mb51_data
            ON fact_mb51_movimentos(data_lancamento);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mb51_movimento
            ON fact_mb51_movimentos(tipo_movimento);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mb51_material_data
            ON fact_mb51_movimentos(material, data_lancamento);
            """
        )

        # ====================================================
        # 3. CADASTRO MATERIAL x POSIÇÃO
        # ====================================================
        #
        # Esta tabela representa a relação entre o material
        # e suas posições cadastradas no SAP.
        #
        # Um material pode possuir várias posições.
        #
        # Exemplos atuais:
        #
        # material
        #   ├── PT02-...
        #   ├── T001-...
        #   └── T001-...
        #
        # Porém o modelo NÃO depende desses códigos.
        #
        # No futuro poderemos receber outros tipos de depósito
        # sem alterar a estrutura do banco.
        #
        # Relação:
        #
        # dim_material 1 ---- N dim_posicao_material
        # ====================================================

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dim_posicao_material (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                material TEXT NOT NULL,

                deposito TEXT NOT NULL,
                tipo_deposito TEXT NOT NULL,
                posicao TEXT NOT NULL,

                quantidade_minima REAL,
                quantidade_maxima REAL,
                unidade_medida TEXT,

                data_modificacao TEXT,
                momento_criacao TEXT,
                autor TEXT,

                arquivo_origem TEXT,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT fk_posicao_material
                    FOREIGN KEY (material)
                    REFERENCES dim_material(material)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT,

                CONSTRAINT uq_posicao_material
                    UNIQUE (
                        deposito,
                        tipo_deposito,
                        posicao,
                        material
                    )
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posicao_material
            ON dim_posicao_material(material);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posicao_codigo
            ON dim_posicao_material(posicao);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posicao_tipo
            ON dim_posicao_material(tipo_deposito);
            """
        )

        # ====================================================
        # 4. SALDO ATUAL POR MATERIAL/POSIÇÃO
        # ====================================================
        #
        # A Visão Geral fornece o snapshot operacional atual
        # por combinação material + posição + tipo de estoque.
        #
        # Uma mesma posição/material pode possuir mais de um
        # tipo de estoque simultaneamente, por exemplo:
        #
        # - F5 = Livre Assist.Tecnic
        # - B5 = Bloqueado Assistencia tecnica
        #
        # Por isso, a unicidade correta é:
        #
        # id_posicao_material + tipo_estoque
        #
        # Esta tabela representa somente o estado atual.
        # O histórico diário de saldo, caso seja necessário
        # futuramente, deverá possuir estrutura própria.
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fact_saldo_posicao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                id_posicao_material INTEGER NOT NULL,

                tipo_estoque TEXT NOT NULL,
                denominacao_tipo_estoque TEXT,

                quantidade REAL,
                quantidade_entrada REAL,
                quantidade_saida REAL,
                quantidade_disponivel REAL,

                unidade_medida TEXT,

                arquivo_origem TEXT,
                atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT fk_saldo_posicao
                    FOREIGN KEY (id_posicao_material)
                    REFERENCES dim_posicao_material(id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,

                CONSTRAINT uq_saldo_posicao_tipo
                    UNIQUE (
                        id_posicao_material,
                        tipo_estoque
                    )
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saldo_posicao_material
            ON fact_saldo_posicao(id_posicao_material);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saldo_tipo_estoque
            ON fact_saldo_posicao(tipo_estoque);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saldo_posicao_tipo
            ON fact_saldo_posicao(
                id_posicao_material,
                tipo_estoque
            );
            """
        )

        # ====================================================
        # 5. FONTES DA RELAÇÃO MATERIAL x POSIÇÃO
        # ====================================================
        #
        # Uma relação material/posição pode aparecer em mais
        # de uma fonte, por exemplo:
        #
        # - BINMAT
        # - VISAO_GERAL
        #
        # Esta tabela registra a proveniência da relação e se
        # ela está presente no snapshot atual daquela fonte.
        #
        # Isso permite distinguir:
        #
        # - relação atual no BINMAT
        # - relação atual somente na Visão Geral
        # - relação histórica que já não está mais presente
        #
        # sem excluir a identidade em dim_posicao_material.
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS posicao_material_fontes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                id_posicao_material INTEGER NOT NULL,

                fonte TEXT NOT NULL,

                primeira_ocorrencia TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultima_ocorrencia TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                arquivo_origem TEXT,

                presente_atual INTEGER NOT NULL DEFAULT 1
                    CHECK (presente_atual IN (0, 1)),

                CONSTRAINT fk_posicao_material_fonte
                    FOREIGN KEY (id_posicao_material)
                    REFERENCES dim_posicao_material(id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,

                CONSTRAINT uq_posicao_material_fonte
                    UNIQUE (
                        id_posicao_material,
                        fonte
                    )
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posicao_material_fontes_posicao
            ON posicao_material_fontes(id_posicao_material);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posicao_material_fontes_fonte
            ON posicao_material_fontes(fonte);
            """
        )

        # ====================================================
        # 6. EXECUÇÕES DO ETL
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS etl_execucoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                processo TEXT NOT NULL,

                inicio_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                fim_em TEXT,

                status TEXT NOT NULL DEFAULT 'EM_EXECUCAO',

                linhas_lidas INTEGER DEFAULT 0,
                linhas_inseridas INTEGER DEFAULT 0,
                linhas_atualizadas INTEGER DEFAULT 0,
                linhas_ignoradas INTEGER DEFAULT 0,
                linhas_com_erro INTEGER DEFAULT 0,

                mensagem TEXT
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_etl_execucoes_processo
            ON etl_execucoes(processo);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_etl_execucoes_inicio
            ON etl_execucoes(inicio_em);
            """
        )

        # ====================================================
        # 7. ARQUIVOS PROCESSADOS PELO ETL
        # ====================================================
        #
        # Agora o arquivo processado também aponta para a
        # execução que efetivamente realizou a carga.
        #
        # Relação:
        #
        # etl_execucoes 1 ---- N etl_arquivos_processados
        #
        # O hash será utilizado futuramente para detectar
        # inclusive arquivos iguais com nomes diferentes.
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS etl_arquivos_processados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                id_execucao INTEGER NOT NULL,

                processo TEXT NOT NULL,
                nome_arquivo TEXT NOT NULL,

                tamanho_bytes INTEGER,
                hash_arquivo TEXT,

                linhas_processadas INTEGER DEFAULT 0,

                processado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT uq_arquivo_hash
                    UNIQUE (processo, hash_arquivo),

                CONSTRAINT fk_arquivo_execucao
                    FOREIGN KEY (id_execucao)
                    REFERENCES etl_execucoes(id)
                    ON UPDATE CASCADE
                    ON DELETE RESTRICT
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_etl_arquivo_execucao
            ON etl_arquivos_processados(id_execucao);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_etl_arquivo_processo
            ON etl_arquivos_processados(processo);
            """
        )

        conn.commit()


    # ========================================================
    # 8. MIGRATIONS DO SCHEMA
    # ========================================================
    #
    # Após criar o schema-base, aplicamos as migrations
    # estruturais conhecidas sobre este mesmo banco.
    #
    # Dessa forma, um banco novo nasce já alinhado com a
    # versão estrutural atual sem duplicar o DDL das migrations
    # dentro deste arquivo.
    # ========================================================

    migration_001 = carregar_migration_001()
    migration_001.aplicar_migration(banco)

    migration_002 = carregar_migration_002()
    migration_002.aplicar_migration(banco)

    print()
    print("Banco criado/validado com sucesso.")
    print()
    print("Tabelas:")
    print("  - dim_material")
    print("  - fact_mb51_movimentos")
    print("  - dim_posicao_material")
    print("  - fact_saldo_posicao")
    print("  - posicao_material_fontes")
    print("  - etl_execucoes")
    print("  - etl_arquivos_processados")
    print("  - schema_migrations")
    print("  - usuarios")
    print("  - plano_parametrizacao")
    print("  - plano_parametrizacao_item")
    print("  - parametrizacao_decisao")
    print("  - parametrizacao_confirmacao")
    print("  - parametrizacao_historico")
    print()
    print("Relacionamentos E/R:")
    print("  dim_material 1:N fact_mb51_movimentos")
    print("  dim_material 1:N dim_posicao_material")
    print("  dim_posicao_material 1:N fact_saldo_posicao")
    print("  dim_posicao_material 1:N posicao_material_fontes")
    print("  etl_execucoes 1:N etl_arquivos_processados")
    print("  plano_parametrizacao 1:N plano_parametrizacao_item")
    print("  plano_parametrizacao_item 1:N parametrizacao_decisao")
    print("  parametrizacao_decisao 1:N parametrizacao_confirmacao")
    print("  plano_parametrizacao_item 1:N parametrizacao_historico")
    print("  usuarios 1:N plano_parametrizacao")
    print("  usuarios 1:N plano_parametrizacao_item")
    print("  usuarios 1:N parametrizacao_decisao")
    print("  usuarios 1:N parametrizacao_historico")
    print()
    print("=" * 70)


if __name__ == "__main__":
    criar_banco()
