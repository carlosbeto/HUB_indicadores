from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import sqlite3

import pandas as pd


# ============================================================
# CAMINHOS DO MÓDULO
# ============================================================
#
# Estrutura esperada:
#
# analiseRessuprimento
# ├── data_db
# │   └── ressuprimento.sqlite
# ├── etl
# │   └── load_mb51.py
# └── INPUT
#     └── MB51
#         └── *.xlsx
#
# Não dependemos do nome específico do arquivo.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"
INPUT_DIR = BASE_DIR / "INPUT" / "MB51"

PROCESSO = "MB51"

# Quantidade de registros enviados ao SQLite por lote.
BATCH_SIZE = 10_000


# ============================================================
# COLUNAS NECESSÁRIAS DA MB51
# ============================================================
#
# Carregaremos apenas os campos necessários para nosso modelo.
#
# IMPORTANTE:
# Não filtramos 601/602/Z17/Z18 aqui.
#
# A MB51 é nossa fato histórica.
# A regra de "demanda relevante" será aplicada posteriormente
# na camada de regras/serviços.
# ============================================================

COLUNAS_MB51 = [
    "Material",
    "Texto breve material",
    "Data de lançamento",
    "Depósito",
    "Cód.débito/crédito",
    "Tipo de movimento",
    "Quantidade",
    "UMB",
    "Doc.material",
    "Item doc.material",
    "Centro custo",
    "Nome do usuário",
]


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def calcular_sha256(caminho: Path) -> str:
    """
    Calcula a impressão digital SHA-256 do arquivo.

    O arquivo é lido em blocos para não precisar carregá-lo
    inteiro na memória.
    """

    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            sha256.update(bloco)

    return sha256.hexdigest()


def normalizar_codigo(valor) -> str | None:
    """
    Normaliza códigos vindos do Excel.

    Exemplos:
        1024710     -> "1024710"
        1024710.0   -> "1024710"
        NaN         -> None

    Usaremos TEXT no SQLite para códigos SAP.
    """

    if pd.isna(valor):
        return None

    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))

    return str(valor).strip()


def normalizar_texto(valor) -> str | None:
    """
    Converte texto vazio/NaN em None e remove espaços
    desnecessários nas extremidades.
    """

    if pd.isna(valor):
        return None

    texto = str(valor).strip()

    return texto if texto else None


def normalizar_quantidade(valor) -> float | None:
    """
    Converte a quantidade para float.

    Mantemos o sinal original informado pela MB51.
    Exemplo:
        601 / H pode aparecer como -20.
    """

    if pd.isna(valor):
        return None

    return float(valor)


# ============================================================
# CONTROLE DO ETL
# ============================================================

def iniciar_execucao(conn: sqlite3.Connection) -> int:
    """
    Registra o início da execução e devolve seu ID.
    """

    cursor = conn.execute(
        """
        INSERT INTO etl_execucoes (
            processo,
            status
        )
        VALUES (?, 'EM_EXECUCAO')
        """,
        (PROCESSO,),
    )

    return cursor.lastrowid


def finalizar_execucao(
    conn: sqlite3.Connection,
    id_execucao: int,
    status: str,
    linhas_lidas: int = 0,
    linhas_inseridas: int = 0,
    linhas_atualizadas: int = 0,
    linhas_ignoradas: int = 0,
    linhas_com_erro: int = 0,
    mensagem: str | None = None,
) -> None:
    """
    Atualiza o registro de auditoria ao final do ETL.
    """

    conn.execute(
        """
        UPDATE etl_execucoes
        SET
            fim_em = CURRENT_TIMESTAMP,
            status = ?,
            linhas_lidas = ?,
            linhas_inseridas = ?,
            linhas_atualizadas = ?,
            linhas_ignoradas = ?,
            linhas_com_erro = ?,
            mensagem = ?
        WHERE id = ?
        """,
        (
            status,
            linhas_lidas,
            linhas_inseridas,
            linhas_atualizadas,
            linhas_ignoradas,
            linhas_com_erro,
            mensagem,
            id_execucao,
        ),
    )


# ============================================================
# CONTROLE DE ARQUIVOS
# ============================================================

def arquivo_ja_processado(
    conn: sqlite3.Connection,
    hash_arquivo: str,
) -> bool:
    """
    Verifica se o mesmo conteúdo já foi processado.

    Não dependemos do nome do arquivo.
    """

    resultado = conn.execute(
        """
        SELECT 1
        FROM etl_arquivos_processados
        WHERE processo = ?
          AND hash_arquivo = ?
        LIMIT 1
        """,
        (PROCESSO, hash_arquivo),
    ).fetchone()

    return resultado is not None


def registrar_arquivo_processado(
    conn: sqlite3.Connection,
    id_execucao: int,
    caminho: Path,
    hash_arquivo: str,
    linhas_processadas: int,
) -> None:
    """
    Registra o arquivo somente depois que sua carga terminou
    com sucesso.
    """

    conn.execute(
        """
        INSERT INTO etl_arquivos_processados (
            id_execucao,
            processo,
            nome_arquivo,
            tamanho_bytes,
            hash_arquivo,
            linhas_processadas
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            id_execucao,
            PROCESSO,
            caminho.name,
            caminho.stat().st_size,
            hash_arquivo,
            linhas_processadas,
        ),
    )


# ============================================================
# VALIDAÇÃO DO ARQUIVO
# ============================================================

def validar_colunas(df: pd.DataFrame, caminho: Path) -> None:
    """
    Garante que a estrutura mínima necessária exista antes
    de qualquer gravação no banco.
    """

    faltantes = [
        coluna
        for coluna in COLUNAS_MB51
        if coluna not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"Arquivo {caminho.name} não possui as colunas "
            f"obrigatórias: {faltantes}"
        )


# ============================================================
# CARGA DA DIMENSÃO MATERIAL
# ============================================================

def carregar_materiais(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
) -> None:
    """
    Insere materiais ainda inexistentes em dim_material.

    Se o material já existir, atualizamos sua descrição
    quando uma descrição válida estiver disponível.
    """

    materiais = (
        df[["material", "descricao_material"]]
        .dropna(subset=["material"])
        .drop_duplicates(subset=["material"], keep="last")
    )

    registros = list(
        materiais.itertuples(index=False, name=None)
    )

    conn.executemany(
        """
        INSERT INTO dim_material (
            material,
            descricao_material
        )
        VALUES (?, ?)

        ON CONFLICT(material)
        DO UPDATE SET
            descricao_material =
                COALESCE(
                    excluded.descricao_material,
                    dim_material.descricao_material
                ),
            atualizado_em = CURRENT_TIMESTAMP
        """,
        registros,
    )


# ============================================================
# CARGA DOS MOVIMENTOS
# ============================================================

def carregar_movimentos(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    nome_arquivo: str,
) -> tuple[int, int]:
    """
    Insere os movimentos MB51.

    A proteção final contra duplicidade está no SQLite:

        UNIQUE(documento_material, item_documento)

    Usamos INSERT OR IGNORE porque uma futura exportação pode
    conter movimentos já existentes e movimentos novos.

    Retorna:
        (linhas_inseridas, linhas_ignoradas)
    """

    sql = """
        INSERT OR IGNORE INTO fact_mb51_movimentos (
            material,
            data_lancamento,
            tipo_movimento,
            debito_credito,
            quantidade,
            unidade_medida_basica,
            documento_material,
            item_documento,
            deposito,
            centro_custo,
            usuario,
            arquivo_origem
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    total_inseridas = 0

    registros = list(
        df[
            [
                "material",
                "data_lancamento",
                "tipo_movimento",
                "debito_credito",
                "quantidade",
                "unidade_medida_basica",
                "documento_material",
                "item_documento",
                "deposito",
                "centro_custo",
                "usuario",
            ]
        ].itertuples(index=False, name=None)
    )

    for inicio in range(0, len(registros), BATCH_SIZE):

        lote = registros[inicio : inicio + BATCH_SIZE]

        antes = conn.total_changes

        conn.executemany(
            sql,
            [
                (*registro, nome_arquivo)
                for registro in lote
            ],
        )

        inseridas_lote = conn.total_changes - antes
        total_inseridas += inseridas_lote

        print(
            f"  Processadas {min(inicio + BATCH_SIZE, len(registros)):,}"
            f" / {len(registros):,} linhas..."
        )

    ignoradas = len(registros) - total_inseridas

    return total_inseridas, ignoradas


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_dataframe(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Converte as colunas do Excel para o formato esperado
    pelo SQLite.
    """

    resultado = pd.DataFrame()

    resultado["material"] = df["Material"].map(
        normalizar_codigo
    )

    resultado["descricao_material"] = df[
        "Texto breve material"
    ].map(normalizar_texto)

    datas = pd.to_datetime(
        df["Data de lançamento"],
        errors="coerce",
    )

    resultado["data_lancamento"] = datas.dt.strftime(
        "%Y-%m-%d"
    )

    resultado["tipo_movimento"] = df[
        "Tipo de movimento"
    ].map(normalizar_codigo)

    resultado["debito_credito"] = df[
        "Cód.débito/crédito"
    ].map(normalizar_texto)

    resultado["quantidade"] = df["Quantidade"].map(
        normalizar_quantidade
    )

    # A quantidade carregada acima está expressa na unidade de medida
    # básica do material (UMB). Mantemos os dois campos juntos para não
    # confundir esse valor com a unidade usada no registro do movimento.
    resultado["unidade_medida_basica"] = df["UMB"].map(
        normalizar_texto
    )

    resultado["documento_material"] = df[
        "Doc.material"
    ].map(normalizar_codigo)

    resultado["item_documento"] = df[
        "Item doc.material"
    ].map(normalizar_codigo)

    resultado["deposito"] = df["Depósito"].map(
        normalizar_texto
    )

    resultado["centro_custo"] = df[
        "Centro custo"
    ].map(normalizar_codigo)

    resultado["usuario"] = df[
        "Nome do usuário"
    ].map(normalizar_texto)

    return resultado


def validar_dados_preparados(
    df: pd.DataFrame,
) -> None:
    """
    Valida campos obrigatórios antes da transação de carga.

    Não queremos descobrir problemas somente quando o SQLite
    tentar inserir a linha.
    """

    obrigatorias = [
        "material",
        "data_lancamento",
        "tipo_movimento",
        "quantidade",
        "unidade_medida_basica",
        "documento_material",
        "item_documento",
    ]

    problemas = df[obrigatorias].isna().sum()

    problemas = problemas[problemas > 0]

    if not problemas.empty:
        raise ValueError(
            "Foram encontrados valores ausentes em campos "
            "obrigatórios:\n"
            f"{problemas.to_string()}"
        )

    duplicadas = df.duplicated(
        subset=[
            "documento_material",
            "item_documento",
        ],
        keep=False,
    )

    if duplicadas.any():
        quantidade = int(duplicadas.sum())

        raise ValueError(
            f"Foram encontradas {quantidade} linhas com "
            "Doc.material + Item doc.material duplicados "
            "dentro do próprio arquivo."
        )


# ============================================================
# PROCESSAMENTO DE UM ARQUIVO
# ============================================================

def processar_arquivo(
    conn: sqlite3.Connection,
    caminho: Path,
) -> None:
    """
    Executa a carga completa de um arquivo MB51.
    """

    print()
    print("-" * 70)
    print(f"Arquivo: {caminho.name}")
    print("-" * 70)

    hash_arquivo = calcular_sha256(caminho)

    print(f"SHA-256: {hash_arquivo}")

    if arquivo_ja_processado(conn, hash_arquivo):
        print("Arquivo já processado. Carga ignorada.")
        return

    id_execucao = iniciar_execucao(conn)
    conn.commit()

    linhas_lidas = 0

    try:
        print("Lendo Excel...")

        df_original = pd.read_excel(
            caminho,
            usecols=COLUNAS_MB51,
        )

        linhas_lidas = len(df_original)

        print(f"Linhas lidas: {linhas_lidas:,}")

        validar_colunas(df_original, caminho)

        print("Normalizando dados...")

        df = preparar_dataframe(df_original)

        print("Validando dados...")

        validar_dados_preparados(df)

        # ----------------------------------------------------
        # A partir daqui começa a carga lógica.
        #
        # Se qualquer etapa falhar, fazemos rollback.
        # ----------------------------------------------------

        conn.execute("BEGIN")

        print("Atualizando dim_material...")

        carregar_materiais(conn, df)

        print("Carregando movimentos MB51...")

        inseridas, ignoradas = carregar_movimentos(
            conn,
            df,
            caminho.name,
        )

        registrar_arquivo_processado(
            conn,
            id_execucao,
            caminho,
            hash_arquivo,
            linhas_lidas,
        )

        finalizar_execucao(
            conn,
            id_execucao,
            status="SUCESSO",
            linhas_lidas=linhas_lidas,
            linhas_inseridas=inseridas,
            linhas_ignoradas=ignoradas,
            mensagem="Carga concluída com sucesso.",
        )

        conn.commit()

        print()
        print("Carga concluída.")
        print(f"  Lidas:      {linhas_lidas:,}")
        print(f"  Inseridas:  {inseridas:,}")
        print(f"  Ignoradas:  {ignoradas:,}")

    except Exception as erro:

        conn.rollback()

        # O registro inicial da execução foi commitado antes
        # da carga. Assim conseguimos registrar a falha mesmo
        # depois do rollback dos dados.
        finalizar_execucao(
            conn,
            id_execucao,
            status="ERRO",
            linhas_lidas=linhas_lidas,
            linhas_com_erro=linhas_lidas,
            mensagem=str(erro),
        )

        conn.commit()

        raise


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:

    print("=" * 70)
    print("ETL MB51 - ANALISE RESSUPRIMENTO")
    print("=" * 70)
    print(f"Banco: {DB_PATH}")
    print(f"INPUT: {INPUT_DIR}")

    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Banco não encontrado. Execute primeiro "
            "etl\\create_database.py"
        )

    arquivos = sorted(INPUT_DIR.glob("*.xlsx"))

    # Ignora arquivos temporários criados pelo próprio Excel.
    arquivos = [
        arquivo
        for arquivo in arquivos
        if not arquivo.name.startswith("~$")
    ]

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo .xlsx encontrado em {INPUT_DIR}"
        )

    print(f"Arquivos encontrados: {len(arquivos)}")

    with sqlite3.connect(DB_PATH) as conn:

        conn.execute("PRAGMA foreign_keys = ON;")

        for arquivo in arquivos:
            processar_arquivo(conn, arquivo)

    print()
    print("=" * 70)
    print("ETL MB51 FINALIZADO")
    print("=" * 70)


if __name__ == "__main__":
    main()
