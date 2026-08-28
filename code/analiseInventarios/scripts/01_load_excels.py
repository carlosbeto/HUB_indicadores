from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Iterable

import pandas as pd


# ====== Caminhos do projeto atual (HUB) ======
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MM_DIR = PROJECT_ROOT / "MM_IN"
EWM_DIR = PROJECT_ROOT / "EWM_IN"
DB_PATH = PROJECT_ROOT / "data_db" / "inventarios.sqlite"
SHEET_NAME = "Data"
# =============================================


MM_COLS = {
    "inv_doc": "Documento inventário",
    "inv_item": "Item",
    "material": "Material",
    "warehouse_code": "Depósito",
    "count_date": "Data contagem",
    "qty_recorded": "Qtd.registrada",
    "qty_counted": "Qtd.contada",
    "qty_diff": "Qtd.diferença",
    "status": "Status invent.físico",
    "counted_by": "Contado por",
    "stock_type": "Tipo de estoque",
}

EWM_COLS = {
    "inv_doc": "DocInvFísico",
    "inv_item": "Item",
    "material": "Produto",
    "warehouse_code": "Tipo de depósito",
    "count_date": "Data de lançamento",
    "qty_recorded": "Qtd.registrada",
    "qty_counted": "Qtd.cont.inv.",
    "qty_diff": "Quantidade de diferença",
    "value_diff": "Valor de diferença",
    "status": "Status do inventário físico",
    "counted_by": "Contador",
    "storage_area": "Área armazmto.",
    "bin_location": "Posição no depósito",
    "stock_type": "Tipo de estoque",
    "wh_order": "Ordem de depósito",
    "count_method": "Método de inventário físico",
}


INSERT_SQL = """
INSERT OR REPLACE INTO counts (
  row_uid, source_system, doc_key, item_key,
  inv_doc, inv_item, material, warehouse_code, logical_warehouse,
  count_date, qty_recorded, qty_counted, qty_diff, value_diff,
  status, counted_by,
  storage_area, bin_location, stock_type, wh_order, count_method,
  year_iso, week_iso, week_start, week_end,
  file_name, loaded_at
) VALUES (
  :row_uid, :source_system, :doc_key, :item_key,
  :inv_doc, :inv_item, :material, :warehouse_code, :logical_warehouse,
  :count_date, :qty_recorded, :qty_counted, :qty_diff, :value_diff,
  :status, :counted_by,
  :storage_area, :bin_location, :stock_type, :wh_order, :count_method,
  :year_iso, :week_iso, :week_start, :week_end,
  :file_name, :loaded_at
);
"""

def _to_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        if isinstance(x, float) and pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def _to_date_iso(x: Any) -> Optional[str]:
    if x is None:
        return None

    if isinstance(x, pd.Timestamp):
        if pd.isna(x):
            return None
        return x.date().isoformat()

    if isinstance(x, datetime):
        return x.date().isoformat()

    if isinstance(x, date):
        return x.isoformat()

    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None

    ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date().isoformat()


def _iso_week_bounds(year_iso: int, week_iso: int) -> tuple[str, str]:
    start = date.fromisocalendar(year_iso, week_iso, 1)  # Monday
    end = date.fromisocalendar(year_iso, week_iso, 7)    # Sunday
    return start.isoformat(), end.isoformat()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def list_xlsx(folder: Path) -> list[Path]:
    """
    Lista os arquivos Excel válidos disponíveis na pasta de entrada.

    O nome do arquivo não participa da seleção. Isso é intencional:
    relatórios exportados pelo SAP podem ter nomes diferentes ou ser
    renomeados pelos usuários sem alterar o conteúdo operacional.
    """
    if not folder.exists():
        return []

    return [
        path
        for path in folder.glob("*.xlsx")
        if path.is_file()
        and not path.name.startswith("~$")
    ]


def choose_latest_xlsx(folder: Path) -> Optional[Path]:
    """
    Seleciona o arquivo Excel fisicamente mais recente da pasta.

    A data de modificação (st_mtime) serve apenas para identificar qual
    exportação deve ser processada. O período real do inventário continua
    sendo determinado pelas datas existentes dentro do relatório SAP.
    """
    files = list_xlsx(folder)

    if not files:
        return None

    return max(files, key=lambda path: path.stat().st_mtime)


def find_missing_sources(
    selected_files: dict[str, Optional[Path]],
) -> list[str]:
    """
    Identifica fontes obrigatórias que não possuem arquivo válido.

    Esta função não acessa o banco nem altera arquivos. Ela existe
    separadamente para tornar explícito e testável o contrato de que
    o ETL completo exige todas as fontes de Inventários.
    """
    return [
        source
        for source, file_path in selected_files.items()
        if file_path is None
    ]

def read_excel(path: Path) -> pd.DataFrame:
    # Aba padrão: "Data"
    return pd.read_excel(path, sheet_name=SHEET_NAME)


def _validate_cols(df: pd.DataFrame, mapping: dict[str, str], file_name: str, source: str) -> None:
    missing = [col for col in mapping.values() if col not in df.columns]
    if missing:
        raise ValueError(f"{source} | {file_name}: faltam colunas esperadas: {missing}")


def build_rows(df: pd.DataFrame, source_system: str, file_name: str, loaded_at: str) -> list[dict]:
    cols = MM_COLS if source_system == "MM" else EWM_COLS
    _validate_cols(df, cols, file_name, source_system)

    out: list[dict] = []

    for _, r in df.iterrows():
        inv_doc = _to_str(r.get(cols["inv_doc"]))
        inv_item = _to_str(r.get(cols["inv_item"]))
        material = _to_str(r.get(cols["material"]))
        warehouse_code = _to_str(r.get(cols["warehouse_code"]))

        # Depósito lógico:
        #
        # MM:
        # O próprio campo "Depósito" identifica diretamente o depósito
        # operacional (MAST, MASR etc.).
        #
        # EWM:
        # O relatório de inventário não possui atualmente uma coluna que
        # identifique diretamente o depósito lógico (WEPV/WAST). O campo
        # "Tipo de depósito" representa a estrutura interna do EWM
        # (T001, PT02, TA01 etc.), portanto não pode ser usado como depósito
        # lógico.
        #
        # Todo o histórico EWM existente pertence ao WEPV. Quando o WAST
        # entrar em operação, esta regra deverá ser substituída pela
        # identificação oficial WEPV/WAST definida para os novos relatórios.
        if source_system == "MM":
            logical_warehouse = warehouse_code
        else:
            logical_warehouse = "WEPV"

        count_date = _to_date_iso(r.get(cols["count_date"]))

        year_iso = week_iso = None
        week_start = week_end = None
        if count_date:
            y, w, _ = date.fromisoformat(count_date).isocalendar()
            year_iso = int(y)
            week_iso = int(w)
            week_start, week_end = _iso_week_bounds(year_iso, week_iso)

        qty_recorded = _to_float(r.get(cols.get("qty_recorded", "")))
        qty_counted = _to_float(r.get(cols.get("qty_counted", "")))
        qty_diff = _to_float(r.get(cols.get("qty_diff", "")))
        value_diff = _to_float(r.get(cols.get("value_diff", "")))

        status = _to_str(r.get(cols.get("status", "")))
        counted_by = _to_str(r.get(cols.get("counted_by", "")))

        storage_area = _to_str(r.get(cols.get("storage_area", "")))
        bin_location = _to_str(r.get(cols.get("bin_location", "")))
        stock_type = _to_str(r.get(cols.get("stock_type", "")))
        wh_order = _to_str(r.get(cols.get("wh_order", "")))

        # Método de inventário físico é uma informação específica do EWM.
        # Preservamos os códigos originais do SAP (HS / HL). No MM não há
        # atualmente um campo equivalente, portanto o banco recebe NULL.
        if source_system == "EWM":
            count_method = _to_str(
                r.get(cols.get("count_method", ""))
            ).upper() or None
        else:
            count_method = None

        # Documento (nível doc)
        doc_key = f"{source_system}|{warehouse_code}|{inv_doc}"

        # Item (nível linha funcional) — EWM inclui granularidade pra evitar colisão
        if source_system == "MM":
            item_key = f"{source_system}|{warehouse_code}|{inv_doc}|{inv_item}|{material}"
            storage_area_db = None
            bin_location_db = None
            wh_order_db = None
        else:
            item_key = (
                f"{source_system}|{warehouse_code}|{inv_doc}|{inv_item}|{material}"
                f"|{storage_area}|{bin_location}|{stock_type}|{wh_order}"
            )
            storage_area_db = storage_area or None
            bin_location_db = bin_location or None
            wh_order_db = wh_order or None

        # row_uid estável: atualiza a mesma linha quando reimportar
        row_uid = _sha1(item_key)

        out.append(
            dict(
                row_uid=row_uid,
                source_system=source_system,
                doc_key=doc_key,
                item_key=item_key,
                inv_doc=inv_doc,
                inv_item=inv_item,
                material=material,
                warehouse_code=warehouse_code,
                logical_warehouse=logical_warehouse,
                count_date=count_date,
                qty_recorded=qty_recorded,
                qty_counted=qty_counted,
                qty_diff=qty_diff,
                value_diff=value_diff,
                status=status or None,
                counted_by=counted_by or None,
                storage_area=storage_area_db,
                bin_location=bin_location_db,
                stock_type=stock_type or None,
                wh_order=wh_order_db,
                count_method=count_method,
                year_iso=year_iso,
                week_iso=week_iso,
                week_start=week_start,
                week_end=week_end,
                file_name=file_name,
                loaded_at=loaded_at,
            )
        )

    return out


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise FileNotFoundError(f"Pasta do projeto não encontrada: {PROJECT_ROOT}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Cada pasta representa uma fonte conhecida.
    #
    # O arquivo é escolhido exclusivamente pela data física de modificação.
    # O nome do .xlsx não define fonte, período ou competência.
    selected_files = {
        "MM": choose_latest_xlsx(MM_DIR),
        "EWM": choose_latest_xlsx(EWM_DIR),
    }

    # O ETL completo de Inventários exige as duas fontes.
    #
    # Não permitimos atualização parcial silenciosa: se MM ou EWM estiver
    # ausente, o processo é interrompido antes de qualquer leitura ou gravação.
    missing_sources = find_missing_sources(selected_files)

    if missing_sources:
        print("[ERRO] ETL de Inventários interrompido.")
        print("[ERRO] Fontes obrigatórias sem arquivo .xlsx válido:")

        for source in missing_sources:
            source_dir = MM_DIR if source == "MM" else EWM_DIR
            print(f"       {source} | pasta={source_dir}")

        print("[ERRO] Banco não foi alterado.")
        return

    loaded_at = datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------------
    # Fase 1 — leitura e validação
    #
    # Nenhuma gravação é feita nesta etapa.
    # Assim, se uma fonte estiver com relatório incorreto ou layout
    # incompatível, o ETL falha antes de alterar o banco.
    # ------------------------------------------------------------------
    prepared_loads: list[tuple[str, Path, list[dict]]] = []

    for source, file_path in selected_files.items():
        if file_path is None:
            print(f"[WARN] {source} | nenhum .xlsx encontrado.")
            continue

        # st_mtime identifica somente qual arquivo físico é o mais recente.
        # Ele não representa a data da contagem do inventário.
        modified_at = datetime.fromtimestamp(
            file_path.stat().st_mtime
        ).isoformat(timespec="seconds")

        print(
            f"[INFO] {source} | arquivo selecionado={file_path.name} "
            f"| modificado_em={modified_at}"
        )

        df = read_excel(file_path)

        # build_rows também valida o layout esperado para a fonte.
        # Portanto, um relatório EWM salvo por engano em MM_IN
        # (ou vice-versa) interrompe o ETL antes da gravação.
        rows = build_rows(
            df,
            source_system=source,
            file_name=file_path.name,
            loaded_at=loaded_at,
        )

        # O período é obtido do conteúdo do SAP, nunca do nome do arquivo.
        count_dates = [
            row["count_date"]
            for row in rows
            if row["count_date"] is not None
        ]

        if count_dates:
            period_start = min(count_dates)
            period_end = max(count_dates)

            print(
                f"[INFO] {source} | periodo_dados="
                f"{period_start} a {period_end}"
            )
        else:
            print(
                f"[WARN] {source} | nenhuma data de contagem válida "
                f"encontrada no relatório."
            )

        prepared_loads.append((source, file_path, rows))

    # ------------------------------------------------------------------
    # Fase 2 — persistência
    #
    # Só chegamos aqui depois que todos os arquivos selecionados foram
    # lidos e validados com sucesso.
    # ------------------------------------------------------------------
    conn = sqlite3.connect(DB_PATH)

    try:
        total_files = 0
        total_rows = 0

        with conn:
            for source, file_path, rows in prepared_loads:
                conn.executemany(INSERT_SQL, rows)

                total_files += 1
                total_rows += len(rows)

                print(
                    f"[OK] {source} | {file_path.name} "
                    f"| linhas={len(rows)}"
                )

        print(
            f"[DONE] arquivos={total_files} "
            f"| linhas_processadas={total_rows}"
        )
        print(f"[DONE] db={DB_PATH}")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
