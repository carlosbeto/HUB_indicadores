from __future__ import annotations

"""Retropreenche a UMB dos movimentos MB51 já armazenados.

O script usa o snapshot acumulado mais recente da pasta INPUT/MB51 e localiza
cada movimento pela chave natural já homologada: documento material + item.
Somente unidades nulas ou vazias são preenchidas; valores existentes nunca
são substituídos. Por isso a execução é idempotente.
"""

from pathlib import Path
import sqlite3

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data_db" / "ressuprimento.sqlite"
INPUT_DIR = BASE_DIR / "INPUT" / "MB51"
BATCH_SIZE = 10_000

COLUNAS_UNIDADE = ["Doc.material", "Item doc.material", "UMB"]


def normalizar_codigo(valor) -> str | None:
    """Normaliza códigos SAP lidos pelo pandas como texto ou número."""

    if pd.isna(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def normalizar_texto(valor) -> str | None:
    """Remove espaços e converte células vazias em ausência explícita."""

    if pd.isna(valor):
        return None
    texto = str(valor).strip()
    return texto if texto else None


def selecionar_snapshot_mais_recente(input_dir: Path) -> Path:
    """Seleciona o Excel mais recentemente modificado, ignorando temporários."""

    arquivos = [
        caminho
        for caminho in input_dir.glob("*.xlsx")
        if not caminho.name.startswith("~$")
    ]
    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo .xlsx encontrado em {input_dir}"
        )
    return max(arquivos, key=lambda caminho: caminho.stat().st_mtime)


def preparar_unidades(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza chave natural e UMB e rejeita dados ambíguos."""

    faltantes = [
        coluna for coluna in COLUNAS_UNIDADE if coluna not in df.columns
    ]
    if faltantes:
        raise ValueError(
            "Colunas obrigatórias ausentes para o retropreenchimento: "
            + ", ".join(faltantes)
        )

    resultado = pd.DataFrame()
    resultado["documento_material"] = df["Doc.material"].map(
        normalizar_codigo
    )
    resultado["item_documento"] = df["Item doc.material"].map(
        normalizar_codigo
    )
    resultado["unidade_medida_basica"] = df["UMB"].map(
        normalizar_texto
    )

    problemas = resultado.isna().sum()
    problemas = problemas[problemas > 0]
    if not problemas.empty:
        raise ValueError(
            "Valores ausentes nos dados usados pelo retropreenchimento:\n"
            + problemas.to_string()
        )

    conflitos = (
        resultado.groupby(
            ["documento_material", "item_documento"],
            dropna=False,
        )["unidade_medida_basica"]
        .nunique()
    )
    if (conflitos > 1).any():
        raise ValueError(
            "Uma mesma chave documento + item possui mais de uma UMB."
        )

    return resultado.drop_duplicates(
        subset=["documento_material", "item_documento"],
        keep="last",
    )


def retropreencher_unidades(
    conn: sqlite3.Connection,
    unidades: pd.DataFrame,
) -> int:
    """Preenche UMBs ausentes e devolve quantos movimentos foram atualizados."""

    sql = """
        UPDATE fact_mb51_movimentos
        SET unidade_medida_basica = ?
        WHERE documento_material = ?
          AND item_documento = ?
          AND (
                unidade_medida_basica IS NULL
                OR TRIM(unidade_medida_basica) = ''
          );
    """

    registros = [
        (
            linha.unidade_medida_basica,
            linha.documento_material,
            linha.item_documento,
        )
        for linha in unidades.itertuples(index=False)
    ]

    antes = conn.total_changes
    for inicio in range(0, len(registros), BATCH_SIZE):
        conn.executemany(sql, registros[inicio : inicio + BATCH_SIZE])

    return conn.total_changes - antes


def main() -> None:
    """Executa o retropreenchimento real em uma única transação."""

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH}")

    snapshot = selecionar_snapshot_mais_recente(INPUT_DIR)
    print("=" * 70)
    print("RETROPREENCIMENTO UMB - MB51")
    print("=" * 70)
    print(f"Banco: {DB_PATH}")
    print(f"Snapshot: {snapshot}")

    df_original = pd.read_excel(snapshot, usecols=COLUNAS_UNIDADE)
    unidades = preparar_unidades(df_original)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE;")
        atualizadas = retropreencher_unidades(conn, unidades)
        pendentes = conn.execute(
            """
            SELECT COUNT(*)
            FROM fact_mb51_movimentos
            WHERE unidade_medida_basica IS NULL
               OR TRIM(unidade_medida_basica) = '';
            """
        ).fetchone()[0]
        conn.commit()

    print(f"Linhas do snapshot: {len(unidades):,}")
    print(f"Movimentos atualizados: {atualizadas:,}")
    print(f"Movimentos ainda sem UMB: {pendentes:,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
