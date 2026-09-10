from __future__ import annotations

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
# │   └── load_binmat.py
# └── INPUT
#     └── BINMAT
#         └── *.xlsx
#
# O ETL não depende de um nome específico de arquivo.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"
INPUT_DIR = BASE_DIR / "INPUT" / "BINMAT"

PROCESSO = "BINMAT"


# ============================================================
# COLUNAS NECESSÁRIAS DA BINMAT
# ============================================================

COLUNAS_BINMAT = [
    "Nº do depósito",
    "Posição no depósito",
    "Tipo de depósito",
    "Produto",
    "Data de modificação",
    "Quantidade máxima",
    "UM exib.qtd.máxima",
    "Qtd.mínima",
    "UM exib.qtd.mínima",
    "Momento de criação",
    "Autor",
]


# ============================================================
# FUNÇÕES DE NORMALIZAÇÃO
# ============================================================

def calcular_sha256(caminho: Path) -> str:
    """
    Calcula a impressão digital SHA-256 do arquivo.

    Arquivos com o mesmo conteúdo terão o mesmo hash,
    independentemente do nome.
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
        1131031.0 -> "1131031"
        1002      -> "1002"
        NaN       -> None
    """

    if pd.isna(valor):
        return None

    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))

    texto = str(valor).strip()

    return texto if texto else None


def normalizar_texto(valor) -> str | None:
    """
    Normaliza campos textuais.
    """

    if pd.isna(valor):
        return None

    texto = str(valor).strip()

    return texto if texto else None


def normalizar_numero(valor) -> float | None:
    """
    Converte MIN/MAX para número real.
    """

    if pd.isna(valor):
        return None

    return float(valor)


# ============================================================
# CONTROLE DO ETL
# ============================================================

def iniciar_execucao(conn: sqlite3.Connection) -> int:
    """
    Registra o início da execução.
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
    Finaliza o registro de auditoria do ETL.
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
    Verifica se exatamente o mesmo conteúdo já foi carregado.
    """

    resultado = conn.execute(
        """
        SELECT 1
        FROM etl_arquivos_processados
        WHERE processo = ?
          AND hash_arquivo = ?
        LIMIT 1
        """,
        (
            PROCESSO,
            hash_arquivo,
        ),
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
    Registra o arquivo somente depois da carga bem-sucedida.
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
# VALIDAÇÃO DA ESTRUTURA DO EXCEL
# ============================================================

def validar_colunas(
    df: pd.DataFrame,
    caminho: Path,
) -> None:
    """
    Confere a estrutura mínima exigida antes de qualquer
    gravação no SQLite.
    """

    faltantes = [
        coluna
        for coluna in COLUNAS_BINMAT
        if coluna not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"Arquivo {caminho.name} não possui as colunas "
            f"obrigatórias: {faltantes}"
        )


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_dataframe(
    df_original: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Limpa e normaliza a BINMAT.

    A BINMAT atual possui uma linha estrutural ao final:

        Nº do depósito = (9.787)

    sem Produto, Tipo de depósito e Posição.

    Essa linha não representa uma posição SAP e será
    contabilizada como ignorada, não como erro.
    """

    df = df_original.copy()

    # --------------------------------------------------------
    # 1. Identifica registros operacionais válidos.
    # --------------------------------------------------------
    #
    # Esses quatro campos formam o contexto mínimo necessário
    # para registrar uma posição.
    # --------------------------------------------------------

    mascara_valida = (
        df["Produto"].notna()
        & df["Nº do depósito"].notna()
        & df["Tipo de depósito"].notna()
        & df["Posição no depósito"].notna()
    )

    ignoradas = int((~mascara_valida).sum())

    df = df.loc[mascara_valida].copy()

    # --------------------------------------------------------
    # 2. Valida as unidades de MIN e MAX.
    #
    # Regra de negócio confirmada:
    # MIN e MAX representam a mesma unidade física do item.
    #
    # Se ambas estiverem preenchidas e diferentes,
    # há inconsistência no arquivo de origem.
    # --------------------------------------------------------

    um_min = df["UM exib.qtd.mínima"].map(normalizar_texto)
    um_max = df["UM exib.qtd.máxima"].map(normalizar_texto)

    divergencia_um = (
        um_min.notna()
        & um_max.notna()
        & um_min.ne(um_max)
    )

    if divergencia_um.any():
        exemplos = df.loc[
            divergencia_um,
            [
                "Produto",
                "Posição no depósito",
                "UM exib.qtd.mínima",
                "UM exib.qtd.máxima",
            ],
        ].head(10)

        raise ValueError(
            "Foram encontradas unidades diferentes entre "
            "MIN e MAX.\n\n"
            f"{exemplos.to_string(index=False)}"
        )

    # Uma única unidade é armazenada no banco.
    unidade_medida = um_min.fillna(um_max)

    # --------------------------------------------------------
    # 3. Montagem do DataFrame normalizado.
    # --------------------------------------------------------

    resultado = pd.DataFrame()

    resultado["material"] = df["Produto"].map(
        normalizar_codigo
    )

    resultado["deposito"] = df[
        "Nº do depósito"
    ].map(normalizar_codigo)

    resultado["tipo_deposito"] = df[
        "Tipo de depósito"
    ].map(normalizar_texto)

    resultado["posicao"] = df[
        "Posição no depósito"
    ].map(normalizar_texto)

    resultado["quantidade_minima"] = df[
        "Qtd.mínima"
    ].map(normalizar_numero)

    resultado["quantidade_maxima"] = df[
        "Quantidade máxima"
    ].map(normalizar_numero)

    resultado["unidade_medida"] = unidade_medida

    # Data de modificação já veio como datetime64 na inspeção,
    # mas usamos conversão explícita para segurança.
    data_modificacao = pd.to_datetime(
        df["Data de modificação"],
        errors="coerce",
    )

    resultado["data_modificacao"] = (
        data_modificacao.dt.strftime("%Y-%m-%d")
    )

    # Momento de criação veio no Excel como texto:
    #
    # 09.01.2025 16:24:01
    #
    # Usamos dayfirst=True para respeitar o padrão brasileiro.
    momento_criacao = pd.to_datetime(
        df["Momento de criação"],
        errors="coerce",
        dayfirst=True,
    )

    resultado["momento_criacao"] = (
        momento_criacao.dt.strftime("%Y-%m-%d %H:%M:%S")
    )

    resultado["autor"] = df["Autor"].map(
        normalizar_texto
    )

    return resultado, ignoradas


# ============================================================
# VALIDAÇÃO DOS REGISTROS NORMALIZADOS
# ============================================================

def validar_dados_preparados(
    df: pd.DataFrame,
) -> None:
    """
    Valida a chave e os campos obrigatórios antes da carga.
    """

    obrigatorias = [
        "material",
        "deposito",
        "tipo_deposito",
        "posicao",
    ]

    problemas = df[obrigatorias].isna().sum()
    problemas = problemas[problemas > 0]

    if not problemas.empty:
        raise ValueError(
            "Existem valores ausentes em campos obrigatórios "
            "após a normalização:\n"
            f"{problemas.to_string()}"
        )

    # A chave natural definida para a tabela é:
    #
    # deposito + tipo_deposito + posicao + material
    #
    duplicadas = df.duplicated(
        subset=[
            "deposito",
            "tipo_deposito",
            "posicao",
            "material",
        ],
        keep=False,
    )

    if duplicadas.any():
        quantidade = int(duplicadas.sum())

        exemplos = df.loc[
            duplicadas,
            [
                "deposito",
                "tipo_deposito",
                "posicao",
                "material",
            ],
        ].head(20)

        raise ValueError(
            f"Foram encontradas {quantidade} linhas "
            "duplicadas pela chave da BINMAT.\n\n"
            f"{exemplos.to_string(index=False)}"
        )


# ============================================================
# DIMENSÃO MATERIAL
# ============================================================

def garantir_materiais(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
) -> int:
    """
    Garante que todo Produto da BINMAT exista em dim_material.

    A MB51 já cadastrou 10.084 materiais, porém a BINMAT pode
    eventualmente possuir algum produto sem movimentação MB51.

    Nesse caso criamos somente o código do material.
    A descrição poderá ser preenchida posteriormente por outra
    fonte oficial.

    Retorna a quantidade de novos materiais inseridos.
    """

    materiais = (
        df["material"]
        .dropna()
        .drop_duplicates()
        .tolist()
    )

    existentes = {
        linha[0]
        for linha in conn.execute(
            """
            SELECT material
            FROM dim_material
            """
        )
    }

    novos = [
        material
        for material in materiais
        if material not in existentes
    ]

    if novos:
        conn.executemany(
            """
            INSERT INTO dim_material (
                material
            )
            VALUES (?)
            """,
            [(material,) for material in novos],
        )

    return len(novos)


# ============================================================
# CARGA DAS POSIÇÕES
# ============================================================

def carregar_posicoes(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    nome_arquivo: str,
) -> tuple[int, int]:
    """
    Insere novas posições e atualiza posições já existentes.

    Chave:

        deposito
        + tipo_deposito
        + posicao
        + material

    Nesta primeira versão NÃO removemos posições ausentes
    no novo arquivo.

    Isso é proposital: a futura Visão Geral poderá cadastrar
    posições T001 que não existem na BINMAT.
    A política de desativação será definida depois que as duas
    fontes estiverem integradas.
    """

    # --------------------------------------------------------
    # Descobrimos as chaves que já existem antes do UPSERT.
    #
    # Isso nos permite registrar corretamente:
    # inseridas x atualizadas
    # --------------------------------------------------------

    chaves_existentes = {
        (
            linha[0],
            linha[1],
            linha[2],
            linha[3],
        )
        for linha in conn.execute(
            """
            SELECT
                deposito,
                tipo_deposito,
                posicao,
                material
            FROM dim_posicao_material
            """
        )
    }

    registros = []

    inseridas = 0
    atualizadas = 0

    for linha in df.itertuples(index=False):

        chave = (
            linha.deposito,
            linha.tipo_deposito,
            linha.posicao,
            linha.material,
        )

        if chave in chaves_existentes:
            atualizadas += 1
        else:
            inseridas += 1

        registros.append(
            (
                linha.material,
                linha.deposito,
                linha.tipo_deposito,
                linha.posicao,
                linha.quantidade_minima,
                linha.quantidade_maxima,
                linha.unidade_medida,
                linha.data_modificacao,
                linha.momento_criacao,
                linha.autor,
                nome_arquivo,
            )
        )

    conn.executemany(
        """
        INSERT INTO dim_posicao_material (
            material,
            deposito,
            tipo_deposito,
            posicao,
            quantidade_minima,
            quantidade_maxima,
            unidade_medida,
            data_modificacao,
            momento_criacao,
            autor,
            arquivo_origem
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT (
            deposito,
            tipo_deposito,
            posicao,
            material
        )
        DO UPDATE SET
            quantidade_minima = excluded.quantidade_minima,
            quantidade_maxima = excluded.quantidade_maxima,
            unidade_medida = excluded.unidade_medida,
            data_modificacao = excluded.data_modificacao,
            momento_criacao = excluded.momento_criacao,
            autor = excluded.autor,
            arquivo_origem = excluded.arquivo_origem,
            atualizado_em = CURRENT_TIMESTAMP
        """,
        registros,
    )

    return inseridas, atualizadas


# ============================================================
# PROCESSAMENTO DO ARQUIVO
# ============================================================

def processar_arquivo(
    conn: sqlite3.Connection,
    caminho: Path,
) -> None:
    """
    Executa todo o processamento de uma BINMAT.
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

    # --------------------------------------------------------
    # A execução é registrada e commitada antes da carga.
    #
    # Assim, mesmo se ocorrer rollback dos dados,
    # conseguimos manter a auditoria da falha.
    # --------------------------------------------------------

    id_execucao = iniciar_execucao(conn)
    conn.commit()

    linhas_lidas = 0
    linhas_ignoradas = 0

    try:

        print("Lendo Excel...")

        df_original = pd.read_excel(
            caminho,
            usecols=COLUNAS_BINMAT,
        )

        linhas_lidas = len(df_original)

        print(f"Linhas lidas: {linhas_lidas:,}")

        validar_colunas(
            df_original,
            caminho,
        )

        print("Normalizando dados...")

        df, linhas_ignoradas = preparar_dataframe(
            df_original
        )

        print(
            f"Registros válidos: {len(df):,}"
        )

        print(
            f"Linhas estruturais ignoradas: "
            f"{linhas_ignoradas:,}"
        )

        print("Validando dados...")

        validar_dados_preparados(df)

        # ----------------------------------------------------
        # A partir daqui iniciamos a transação de gravação.
        # ----------------------------------------------------

        conn.execute("BEGIN")

        print("Garantindo materiais em dim_material...")

        novos_materiais = garantir_materiais(
            conn,
            df,
        )

        print(
            f"Novos materiais cadastrados: "
            f"{novos_materiais:,}"
        )

        print("Carregando posições BINMAT...")

        inseridas, atualizadas = carregar_posicoes(
            conn,
            df,
            caminho.name,
        )

        registrar_arquivo_processado(
            conn,
            id_execucao,
            caminho,
            hash_arquivo,
            len(df),
        )

        finalizar_execucao(
            conn,
            id_execucao,
            status="SUCESSO",
            linhas_lidas=linhas_lidas,
            linhas_inseridas=inseridas,
            linhas_atualizadas=atualizadas,
            linhas_ignoradas=linhas_ignoradas,
            linhas_com_erro=0,
            mensagem=(
                "Carga BINMAT concluída com sucesso. "
                f"Novos materiais: {novos_materiais}."
            ),
        )

        conn.commit()

        print()
        print("Carga concluída.")
        print(f"  Lidas:       {linhas_lidas:,}")
        print(f"  Válidas:     {len(df):,}")
        print(f"  Inseridas:   {inseridas:,}")
        print(f"  Atualizadas: {atualizadas:,}")
        print(f"  Ignoradas:   {linhas_ignoradas:,}")

    except Exception as erro:

        conn.rollback()

        finalizar_execucao(
            conn,
            id_execucao,
            status="ERRO",
            linhas_lidas=linhas_lidas,
            linhas_ignoradas=linhas_ignoradas,
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
    print("ETL BINMAT - ANALISE RESSUPRIMENTO")
    print("=" * 70)

    print(f"Banco: {DB_PATH}")
    print(f"INPUT: {INPUT_DIR}")

    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Banco não encontrado. Execute primeiro "
            "etl\\create_database.py"
        )

    arquivos = sorted(
        INPUT_DIR.glob("*.xlsx")
    )

    # Ignora arquivos temporários do Excel (~$...)
    arquivos = [
        arquivo
        for arquivo in arquivos
        if not arquivo.name.startswith("~$")
    ]

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo .xlsx encontrado em "
            f"{INPUT_DIR}"
        )

    print(
        f"Arquivos encontrados: {len(arquivos)}"
    )

    with sqlite3.connect(DB_PATH) as conn:

        # Obrigatório em toda conexão SQLite deste módulo.
        conn.execute(
            "PRAGMA foreign_keys = ON;"
        )

        for arquivo in arquivos:
            processar_arquivo(
                conn,
                arquivo,
            )

    print()
    print("=" * 70)
    print("ETL BINMAT FINALIZADO")
    print("=" * 70)


if __name__ == "__main__":
    main()
