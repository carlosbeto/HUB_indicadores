# code/analiseInventarios/scripts/materiais_snapshot.py
# -*- coding: utf-8 -*-

"""
Leitura e normalização do relatório diário Materiais*.xlsx.

Este módulo concentra somente responsabilidades relacionadas à fonte de
estoque compartilhada pelo HUB.

A mesma fonte é utilizada para finalidades diferentes:

- baseline_items:
  utiliza a primeira foto disponível de cada mês;

- mm_snapshot:
  utiliza a foto mais recente disponível para MAST/MASR.

A escolha da finalidade permanece nos respectivos loaders. Este módulo
cuida apenas da origem, validação e transformação básica dos dados.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


# ------------------------------------------------------------
# CAMINHOS
# ------------------------------------------------------------
# Este arquivo está em:
#
# HUB_indicadores[_DEV]
# └── code
#     └── analiseInventarios
#         └── scripts
#             └── materiais_snapshot.py
#
# Portanto, parents[3] corresponde à raiz do HUB.
HUB_ROOT = Path(__file__).resolve().parents[3]

# Fonte oficial do saldo diário dos depósitos.
SAP_IN_DIR = HUB_ROOT / "data" / "analiseEstoques" / "SAP_IN"


# ------------------------------------------------------------
# COLUNAS ESPERADAS NO EXCEL DE ESTOQUE
# ------------------------------------------------------------
REQUIRED_COLUMNS = {
    "Material",
    "Descrição de material",
    "Depósito",
    "Estoque de utilização livre",
    "Estoque em controle de qualidade",
    "Estoque bloqueado",
    "Valor do estoque de utilização livre",
    "Valor do estoque no controle de qualidade",
    "Valor do estoque bloqueado",
}

# ------------------------------------------------------------
# CONVERSÕES
# ------------------------------------------------------------
def to_float_ptbr(valor) -> Optional[float]:
    """
    Converte números recebidos em formato numérico ou textual para float.

    Exemplos:
    - '1.234,56' -> 1234.56
    - '8 PEÇ'    -> 8.0
    - '20,33 BRL' -> 20.33
    - vazio / NaN -> None
    """

    if valor is None or (
        isinstance(valor, float)
        and pd.isna(valor)
    ):
        return None

    texto = str(valor).strip()

    if not texto or texto.lower() == "nan":
        return None

    # Remove textos de unidade/moeda que podem acompanhar o número.
    texto = (
        texto
        .replace("PEÇ", "")
        .replace("BRL", "")
        .strip()
    )

    # Converte a representação pt-BR:
    #
    # 1.234,56 -> 1234.56
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------
# DATA DO SNAPSHOT
# ------------------------------------------------------------
def get_snapshot_info_from_filename(
    file_path: Path,
) -> tuple[str, str]:
    """
    Extrai snapshot_date e snapshot_month do nome Materiais*.xlsx.

    Formatos aceitos:

    MateriaisMMYYYY.xlsx
        Materiais012026.xlsx
        -> 2026-01-01 / 2026-01

    MateriaisDDMMYYYY.xlsx
        Materiais27072026.xlsx
        -> 2026-07-27 / 2026-07
    """

    nome = file_path.stem.replace("Materiais", "").strip()

    # Formato MMYYYY.
    if len(nome) == 6 and nome.isdigit():
        mes = int(nome[0:2])
        ano = int(nome[2:6])

        snapshot_date = f"{ano:04d}-{mes:02d}-01"
        snapshot_month = f"{ano:04d}-{mes:02d}"

        return snapshot_date, snapshot_month

    # Formato DDMMYYYY.
    if len(nome) == 8 and nome.isdigit():
        dia = int(nome[0:2])
        mes = int(nome[2:4])
        ano = int(nome[4:8])

        snapshot_date = f"{ano:04d}-{mes:02d}-{dia:02d}"
        snapshot_month = f"{ano:04d}-{mes:02d}"

        return snapshot_date, snapshot_month

    raise ValueError(
        "Nome de arquivo não reconhecido para extrair snapshot: "
        f"{file_path.name}"
    )


# ------------------------------------------------------------
# DESCOBERTA DOS ARQUIVOS
# ------------------------------------------------------------
def list_material_files() -> list[Path]:
    """
    Lista os arquivos Materiais*.xlsx existentes na fonte oficial.
    """

    if not SAP_IN_DIR.exists():
        raise FileNotFoundError(
            f"Pasta SAP_IN não encontrada: {SAP_IN_DIR}"
        )

    files = [
        path
        for path in SAP_IN_DIR.glob("Materiais*.xlsx")
        if path.is_file()
        and not path.name.startswith("~$")
    ]

    if not files:
        raise FileNotFoundError(
            f"Nenhum Materiais*.xlsx encontrado em {SAP_IN_DIR}"
        )

    return files


def choose_first_file_per_month(
    files: list[Path],
) -> dict[str, Path]:
    """
    Escolhe a primeira foto cronológica disponível de cada mês.

    Esta regra atende ao baseline mensal.
    """

    month_to_file: dict[str, tuple[str, Path]] = {}

    for file_path in files:
        snapshot_date, snapshot_month = (
            get_snapshot_info_from_filename(file_path)
        )

        atual = month_to_file.get(snapshot_month)

        if atual is None or snapshot_date < atual[0]:
            month_to_file[snapshot_month] = (
                snapshot_date,
                file_path,
            )

    return {
        month: file_path
        for month, (_, file_path)
        in month_to_file.items()
    }


def choose_latest_file(
    files: list[Path],
) -> Path:
    """
    Escolhe a foto cronologicamente mais recente.

    Esta regra atende ao snapshot financeiro atual.
    """

    return max(
        files,
        key=lambda file_path: get_snapshot_info_from_filename(
            file_path
        )[0],
    )


# ------------------------------------------------------------
# LEITURA E VALIDAÇÃO
# ------------------------------------------------------------
def validate_columns(
    df: pd.DataFrame,
    file_name: str,
) -> None:
    """
    Confirma que o relatório possui todas as colunas necessárias.
    """

    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"{file_name}: faltam colunas esperadas: {missing}\n"
            f"Colunas encontradas: {list(df.columns)}"
        )


def read_material_excel(
    file_path: Path,
) -> pd.DataFrame:
    """
    Lê um Materiais*.xlsx e valida sua estrutura.
    """

    df = pd.read_excel(file_path)

    validate_columns(
        df,
        file_path.name,
    )

    return df
