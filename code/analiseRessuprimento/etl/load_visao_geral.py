from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import sqlite3

import pandas as pd


# ============================================================
# CAMINHOS E CONFIGURAÇÕES DO MÓDULO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"
INPUT_DIR = BASE_DIR / "INPUT" / "VISAO_GERAL"

PROCESSO = "VISAO_GERAL"

# Este módulo de ressuprimento trabalha atualmente
# exclusivamente com o depósito/planta 1002.
DEPOSITO = "1002"


# ============================================================
# COLUNAS NECESSÁRIAS DA VISAO_GERAL
# ============================================================

COLUNAS_VISAO_GERAL = [
    "Tipo de depósito",
    "Posição no depósito",
    "Produto",
    "Descrição produto",
    "Quantidade",
    "Tipo de estoque",
    "Denom.tipo estoque",
    "Qtd.entrada",
    "Quantidade de saída",
    "Qtd.disponível UMB",
    "UM básica",
]


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def calcular_sha256(caminho: Path) -> str:
    """
    Calcula a impressão digital SHA-256 do arquivo.

    O controle é feito pelo conteúdo do arquivo,
    independentemente do nome.
    """

    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            sha256.update(bloco)

    return sha256.hexdigest()


def normalizar_codigo(valor) -> str | None:
    """
    Normaliza códigos SAP vindos do Excel.

    Exemplos:
        1024435.0 -> "1024435"
        1024435   -> "1024435"
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
    Converte quantidades SAP para float.
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
    Verifica se exatamente o mesmo conteúdo já foi processado.
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

def snapshot_atual_eh_arquivo(
    conn: sqlite3.Connection,
    nome_arquivo: str,
) -> bool:
    """
    Verifica se a fact_saldo_posicao já representa
    integralmente o arquivo selecionado como snapshot atual.

    Para VISAO_GERAL, um arquivo pode ter sido processado
    anteriormente e mesmo assim não ser mais a fotografia
    materializada no banco, caso outro snapshot tenha sido
    carregado depois.
    """

    resultado = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(
                CASE
                    WHEN arquivo_origem = ? THEN 1
                END
            ) AS total_arquivo
        FROM fact_saldo_posicao
        """,
        (nome_arquivo,),
    ).fetchone()

    total = resultado[0]
    total_arquivo = resultado[1]

    return (
        total > 0
        and total == total_arquivo
    )


def registrar_arquivo_processado(
    conn: sqlite3.Connection,
    id_execucao: int,
    caminho: Path,
    hash_arquivo: str,
    linhas_processadas: int,
) -> None:
    """
    Registra o arquivo somente após a carga bem-sucedida.
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
# VALIDAÇÃO DA ESTRUTURA
# ============================================================

def validar_colunas(
    df: pd.DataFrame,
    caminho: Path,
) -> None:
    """
    Confere a estrutura mínima da VISAO_GERAL.
    """

    faltantes = [
        coluna
        for coluna in COLUNAS_VISAO_GERAL
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
    Normaliza a fotografia atual da VISAO_GERAL.

    Linhas sem Produto, Tipo de depósito ou Posição
    não representam relações operacionais válidas.
    """

    df = df_original.copy()

    mascara_valida = (
        df["Produto"].notna()
        & df["Tipo de depósito"].notna()
        & df["Posição no depósito"].notna()
    )

    ignoradas = int((~mascara_valida).sum())

    df = df.loc[mascara_valida].copy()

    resultado = pd.DataFrame()

    resultado["material"] = df[
        "Produto"
    ].map(normalizar_codigo)

    resultado["descricao_material"] = df[
        "Descrição produto"
    ].map(normalizar_texto)

    resultado["deposito"] = DEPOSITO

    resultado["tipo_deposito"] = df[
        "Tipo de depósito"
    ].map(normalizar_texto)

    resultado["posicao"] = df[
        "Posição no depósito"
    ].map(normalizar_texto)

    resultado["tipo_estoque"] = df[
        "Tipo de estoque"
    ].map(normalizar_codigo)

    resultado["denominacao_tipo_estoque"] = df[
        "Denom.tipo estoque"
    ].map(normalizar_texto)

    resultado["quantidade"] = df[
        "Quantidade"
    ].map(normalizar_numero)

    resultado["quantidade_entrada"] = df[
        "Qtd.entrada"
    ].map(normalizar_numero)

    resultado["quantidade_saida"] = df[
        "Quantidade de saída"
    ].map(normalizar_numero)

    resultado["quantidade_disponivel"] = df[
        "Qtd.disponível UMB"
    ].map(normalizar_numero)

    resultado["unidade_medida"] = df[
        "UM básica"
    ].map(normalizar_texto)

    return resultado, ignoradas


# ============================================================
# VALIDAÇÃO DOS DADOS NORMALIZADOS
# ============================================================

def validar_dados_preparados(
    df: pd.DataFrame,
) -> None:
    """
    Valida campos obrigatórios e granularidade do snapshot.

    A granularidade esperada para saldo é:

        depósito
        + tipo de depósito
        + posição
        + material
        + tipo de estoque
    """

    obrigatorias = [
        "material",
        "deposito",
        "tipo_deposito",
        "posicao",
        "tipo_estoque",
    ]

    problemas = df[obrigatorias].isna().sum()
    problemas = problemas[problemas > 0]

    if not problemas.empty:
        raise ValueError(
            "Existem valores ausentes em campos obrigatórios "
            "após a normalização:\n"
            f"{problemas.to_string()}"
        )

    chave = [
        "deposito",
        "tipo_deposito",
        "posicao",
        "material",
        "tipo_estoque",
    ]

    duplicadas = df.duplicated(
        subset=chave,
        keep=False,
    )

    if duplicadas.any():

        quantidade = int(duplicadas.sum())

        exemplos = df.loc[
            duplicadas,
            chave
            + [
                "quantidade",
                "quantidade_disponivel",
            ],
        ].head(20)

        raise ValueError(
            f"Foram encontradas {quantidade} linhas "
            "duplicadas pela granularidade esperada da "
            "VISAO_GERAL.\n\n"
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
    Garante que todos os materiais da VISAO_GERAL existam
    em dim_material.

    Também aproveita a descrição da fonte quando disponível.
    """

    materiais = (
        df[
            [
                "material",
                "descricao_material",
            ]
        ]
        .dropna(subset=["material"])
        .drop_duplicates(
            subset=["material"],
            keep="last",
        )
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
        for material in materiais["material"].tolist()
        if material not in existentes
    ]

    registros = list(
        materiais.itertuples(
            index=False,
            name=None,
        )
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
                    dim_material.descricao_material,
                    excluded.descricao_material
                ),
            atualizado_em = CURRENT_TIMESTAMP
        """,
        registros,
    )

    return len(novos)


# ============================================================
# DIMENSÃO POSIÇÃO/MATERIAL
# ============================================================

def garantir_posicoes(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    nome_arquivo: str,
) -> tuple[int, int]:
    """
    Garante que toda relação posição/material da VISAO_GERAL
    exista em dim_posicao_material.

    Relações já existentes, especialmente as provenientes da
    BINMAT, NÃO têm MIN/MAX nem metadados BINMAT sobrescritos.

    Relações ausentes são criadas pela VISAO_GERAL.

    Isso é esperado principalmente para posições T001 que
    existem fisicamente, mas ainda não estão parametrizadas
    na BINMAT.
    """

    posicoes = (
        df[
            [
                "material",
                "deposito",
                "tipo_deposito",
                "posicao",
                "unidade_medida",
            ]
        ]
        .drop_duplicates(
            subset=[
                "deposito",
                "tipo_deposito",
                "posicao",
                "material",
            ],
            keep="last",
        )
    )

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

    registros_novos = []
    existentes = 0

    for linha in posicoes.itertuples(index=False):

        chave = (
            linha.deposito,
            linha.tipo_deposito,
            linha.posicao,
            linha.material,
        )

        if chave in chaves_existentes:
            existentes += 1
            continue

        registros_novos.append(
            (
                linha.material,
                linha.deposito,
                linha.tipo_deposito,
                linha.posicao,
                linha.unidade_medida,
                nome_arquivo,
            )
        )

    if registros_novos:

        conn.executemany(
            """
            INSERT INTO dim_posicao_material (
                material,
                deposito,
                tipo_deposito,
                posicao,
                unidade_medida,
                arquivo_origem
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            registros_novos,
        )

    return len(registros_novos), existentes


# ============================================================
# PROCEDÊNCIA DAS POSIÇÕES
# ============================================================

def registrar_fontes_visao_geral(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    nome_arquivo: str,
) -> int:
    """
    Sincroniza a presença atual das relações posição/material
    observadas na VISAO_GERAL.

    A VISAO_GERAL é um snapshot completo.

    Portanto:
        1. todas as relações anteriormente associadas à
           VISAO_GERAL são marcadas como não presentes;
        2. as relações encontradas no snapshot atual são
           inseridas ou reativadas;
        3. primeira_ocorrencia preserva o histórico;
        4. ultima_ocorrencia registra a observação mais recente.

    A dim_posicao_material não é apagada.
    """

    # --------------------------------------------------------
    # Como a fonte é snapshot completo, começamos considerando
    # ausentes todas as relações anteriormente conhecidas
    # pela VISAO_GERAL.
    #
    # Somente as encontradas no arquivo atual serão reativadas.
    # Tudo ocorre dentro da transação principal do ETL.
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE posicao_material_fontes
        SET presente_atual = 0
        WHERE fonte = 'VISAO_GERAL'
        """
    )

    chaves = (
        df[
            [
                "deposito",
                "tipo_deposito",
                "posicao",
                "material",
            ]
        ]
        .drop_duplicates()
    )

    registros = []

    for linha in chaves.itertuples(index=False):

        resultado = conn.execute(
            """
            SELECT id
            FROM dim_posicao_material
            WHERE deposito = ?
              AND tipo_deposito = ?
              AND posicao = ?
              AND material = ?
            """,
            (
                linha.deposito,
                linha.tipo_deposito,
                linha.posicao,
                linha.material,
            ),
        ).fetchone()

        if resultado is None:
            raise RuntimeError(
                "Relação posição/material não encontrada "
                "após garantir_posicoes: "
                f"{linha.material} / {linha.posicao}"
            )

        registros.append(
            (
                resultado[0],
                "VISAO_GERAL",
                nome_arquivo,
            )
        )

    conn.executemany(
        """
        INSERT INTO posicao_material_fontes (
            id_posicao_material,
            fonte,
            arquivo_origem,
            presente_atual
        )
        VALUES (?, ?, ?, 1)

        ON CONFLICT (
            id_posicao_material,
            fonte
        )
        DO UPDATE SET
            ultima_ocorrencia = CURRENT_TIMESTAMP,
            arquivo_origem = excluded.arquivo_origem,
            presente_atual = 1
        """,
        registros,
    )

    return len(registros)


# ============================================================
# CARGA DO SNAPSHOT DE SALDOS
# ============================================================

def carregar_saldos(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    nome_arquivo: str,
) -> tuple[int, int]:
    """
    Substitui de forma transacional a fotografia atual
    de fact_saldo_posicao.

    IMPORTANTE:
    VISAO_GERAL é snapshot, não histórico incremental.

    Portanto:
        1. os saldos anteriores são removidos;
        2. a fotografia atual é inserida;
        3. tudo ocorre dentro da mesma transação.

    Se houver qualquer erro antes do COMMIT, o rollback
    restaura a fotografia anterior.
    """

    saldo_anterior = conn.execute(
        """
        SELECT COUNT(*)
        FROM fact_saldo_posicao
        """
    ).fetchone()[0]

    conn.execute(
        """
        DELETE FROM fact_saldo_posicao
        """
    )

    mapa_posicoes = {
        (
            linha[1],
            linha[2],
            linha[3],
            linha[4],
        ): linha[0]
        for linha in conn.execute(
            """
            SELECT
                id,
                deposito,
                tipo_deposito,
                posicao,
                material
            FROM dim_posicao_material
            """
        )
    }

    registros = []

    for linha in df.itertuples(index=False):

        chave = (
            linha.deposito,
            linha.tipo_deposito,
            linha.posicao,
            linha.material,
        )

        id_posicao_material = mapa_posicoes.get(chave)

        if id_posicao_material is None:
            raise RuntimeError(
                "Não foi possível localizar "
                "id_posicao_material para "
                f"{linha.material} / {linha.posicao}"
            )

        registros.append(
            (
                id_posicao_material,
                linha.tipo_estoque,
                linha.denominacao_tipo_estoque,
                linha.quantidade,
                linha.quantidade_entrada,
                linha.quantidade_saida,
                linha.quantidade_disponivel,
                linha.unidade_medida,
                nome_arquivo,
            )
        )

    conn.executemany(
        """
        INSERT INTO fact_saldo_posicao (
            id_posicao_material,
            tipo_estoque,
            denominacao_tipo_estoque,
            quantidade,
            quantidade_entrada,
            quantidade_saida,
            quantidade_disponivel,
            unidade_medida,
            arquivo_origem
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        registros,
    )

    return len(registros), saldo_anterior


# ============================================================
# INDICADORES DA FOTOGRAFIA
# ============================================================

def calcular_resumo(
    conn: sqlite3.Connection,
) -> dict:
    """
    Calcula indicadores básicos após a carga.

    F5 é o único estoque considerado utilizável para
    ressuprimento.

    B5 e demais tipos permanecem armazenados para diagnóstico.
    """

    total_saldos = conn.execute(
        """
        SELECT COUNT(*)
        FROM fact_saldo_posicao
        """
    ).fetchone()[0]

    qtd_f5 = conn.execute(
        """
        SELECT COUNT(*)
        FROM fact_saldo_posicao
        WHERE tipo_estoque = 'F5'
        """
    ).fetchone()[0]

    saldo_f5 = conn.execute(
        """
        SELECT COALESCE(SUM(quantidade_disponivel), 0)
        FROM fact_saldo_posicao
        WHERE tipo_estoque = 'F5'
        """
    ).fetchone()[0]

    qtd_b5 = conn.execute(
        """
        SELECT COUNT(*)
        FROM fact_saldo_posicao
        WHERE tipo_estoque = 'B5'
        """
    ).fetchone()[0]

    saldo_b5 = conn.execute(
        """
        SELECT COALESCE(SUM(quantidade_disponivel), 0)
        FROM fact_saldo_posicao
        WHERE tipo_estoque = 'B5'
        """
    ).fetchone()[0]

    t001_visao = conn.execute(
        """
        SELECT COUNT(DISTINCT d.posicao)
        FROM dim_posicao_material d
        JOIN posicao_material_fontes f
          ON f.id_posicao_material = d.id
        WHERE f.fonte = 'VISAO_GERAL'
          AND f.presente_atual = 1
          AND d.tipo_deposito = 'T001'
        """
    ).fetchone()[0]

    t001_sem_binmat = conn.execute(
        """
        SELECT COUNT(DISTINCT d.id)
        FROM dim_posicao_material d

        JOIN posicao_material_fontes vg
          ON vg.id_posicao_material = d.id
         AND vg.fonte = 'VISAO_GERAL'
         AND vg.presente_atual = 1

        LEFT JOIN posicao_material_fontes bm
          ON bm.id_posicao_material = d.id
         AND bm.fonte = 'BINMAT'
         AND bm.presente_atual = 1

        WHERE d.tipo_deposito = 'T001'
          AND bm.id IS NULL
        """
    ).fetchone()[0]

    return {
        "total_saldos": total_saldos,
        "qtd_f5": qtd_f5,
        "saldo_f5": saldo_f5,
        "qtd_b5": qtd_b5,
        "saldo_b5": saldo_b5,
        "t001_visao": t001_visao,
        "t001_sem_binmat": t001_sem_binmat,
    }


# ============================================================
# PROCESSAMENTO DO ARQUIVO
# ============================================================

def processar_arquivo(
    conn: sqlite3.Connection,
    caminho: Path,
) -> None:
    """
    Executa a carga completa de uma fotografia VISAO_GERAL.
    """

    print()
    print("-" * 70)
    print(f"Arquivo: {caminho.name}")
    print("-" * 70)

    hash_arquivo = calcular_sha256(caminho)

    print(f"SHA-256: {hash_arquivo}")

    ja_processado = arquivo_ja_processado(
        conn,
        hash_arquivo,
    )

    snapshot_ja_atual = snapshot_atual_eh_arquivo(
        conn,
        caminho.name,
    )

    if ja_processado and snapshot_ja_atual:
        print(
            "Arquivo já processado e já representa "
            "o snapshot atual. Carga ignorada."
        )
        return

    if ja_processado and not snapshot_ja_atual:
        print(
            "Arquivo já foi processado anteriormente, "
            "mas não representa o snapshot atual."
        )
        print(
            "O snapshot será restaurado a partir "
            "deste arquivo."
        )

    id_execucao = iniciar_execucao(conn)
    conn.commit()

    linhas_lidas = 0
    linhas_ignoradas = 0

    try:

        print("Lendo Excel...")

        df_original = pd.read_excel(
            caminho,
            usecols=COLUNAS_VISAO_GERAL,
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

        print(f"Registros válidos: {len(df):,}")
        print(
            "Linhas estruturais ignoradas: "
            f"{linhas_ignoradas:,}"
        )

        print("Validando dados...")

        validar_dados_preparados(df)

        # ----------------------------------------------------
        # A partir daqui começa a transação da fotografia.
        #
        # Nenhuma alteração parcial deverá sobreviver a erro.
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

        print("Garantindo relações posição/material...")

        novas_posicoes, posicoes_existentes = garantir_posicoes(
            conn,
            df,
            caminho.name,
        )

        print(
            f"Novas relações criadas: "
            f"{novas_posicoes:,}"
        )

        print(
            f"Relações já existentes: "
            f"{posicoes_existentes:,}"
        )

        print("Registrando procedência VISAO_GERAL...")

        fontes_registradas = registrar_fontes_visao_geral(
            conn,
            df,
            caminho.name,
        )

        print(
            f"Relações observadas na VISAO_GERAL: "
            f"{fontes_registradas:,}"
        )

        print("Sincronizando snapshot de saldos...")

        saldos_inseridos, saldo_anterior = carregar_saldos(
            conn,
            df,
            caminho.name,
        )

        print(
            f"Snapshot anterior: {saldo_anterior:,}"
        )

        print(
            f"Snapshot atual:    {saldos_inseridos:,}"
        )

        resumo = calcular_resumo(conn)

        if not ja_processado:
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
            linhas_inseridas=saldos_inseridos,
            linhas_atualizadas=0,
            linhas_ignoradas=linhas_ignoradas,
            linhas_com_erro=0,
            mensagem=(
                "Carga VISAO_GERAL concluída com sucesso. "
                f"Novos materiais: {novos_materiais}. "
                f"Novas relações posição/material: "
                f"{novas_posicoes}."
            ),
        )

        conn.commit()

        print()
        print("Carga concluída.")
        print(f"  Lidas:                    {linhas_lidas:,}")
        print(f"  Válidas:                  {len(df):,}")
        print(f"  Ignoradas:                {linhas_ignoradas:,}")
        print(f"  Novos materiais:          {novos_materiais:,}")
        print(f"  Novas posições:           {novas_posicoes:,}")
        print(f"  Saldos carregados:        {saldos_inseridos:,}")

        print()
        print("Resumo operacional do snapshot:")
        print(
            f"  Registros F5:             "
            f"{resumo['qtd_f5']:,}"
        )
        print(
            f"  Saldo disponível F5:      "
            f"{resumo['saldo_f5']:,.2f}"
        )
        print(
            f"  Registros B5:             "
            f"{resumo['qtd_b5']:,}"
        )
        print(
            f"  Saldo disponível B5:      "
            f"{resumo['saldo_b5']:,.2f}"
        )
        print(
            f"  Posições T001 observadas: "
            f"{resumo['t001_visao']:,}"
        )
        print(
            "  Relações T001 sem BINMAT: "
            f"{resumo['t001_sem_binmat']:,}"
        )

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
    print("ETL VISAO_GERAL - ANALISE RESSUPRIMENTO")
    print("=" * 70)

    print(f"Banco: {DB_PATH}")
    print(f"INPUT: {INPUT_DIR}")
    print(f"Depósito: {DEPOSITO}")

    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Banco não encontrado. Execute primeiro "
            "etl\\create_database.py"
        )

        # --------------------------------------------------------
    # VISAO_GERAL é uma fotografia do estado atual.
    #
    # Portanto, diferente da MB51, não processamos todos os
    # arquivos encontrados na pasta.
    #
    # Selecionamos somente o arquivo .xlsx com a data de
    # modificação mais recente registrada pelo Windows.
    #
    # O nome do arquivo não participa da decisão.
    # --------------------------------------------------------

    arquivos = [
        arquivo
        for arquivo in INPUT_DIR.glob("*.xlsx")
        if not arquivo.name.startswith("~$")
    ]

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo .xlsx encontrado em "
            f"{INPUT_DIR}"
        )

    arquivo_mais_recente = max(
        arquivos,
        key=lambda arquivo: arquivo.stat().st_mtime,
    )

    data_modificacao = datetime.fromtimestamp(
        arquivo_mais_recente.stat().st_mtime
    )

    print(f"Arquivos encontrados: {len(arquivos)}")
    print(
        "Snapshot selecionado: "
        f"{arquivo_mais_recente.name}"
    )
    print(
        "Data de modificação: "
        f"{data_modificacao:%Y-%m-%d %H:%M:%S}"
    )

    with sqlite3.connect(DB_PATH) as conn:

        conn.execute(
            "PRAGMA foreign_keys = ON;"
        )

        processar_arquivo(
            conn,
            arquivo_mais_recente,
        )

    print()
    print("=" * 70)
    print("ETL VISAO_GERAL FINALIZADO")
    print("=" * 70)


if __name__ == "__main__":
    main()
