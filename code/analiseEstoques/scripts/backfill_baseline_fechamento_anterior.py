from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from analiseEstoques.scripts.update_from_sap import compute_and_store_kpi


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = PROJECT_ROOT / "data" / "analiseEstoques" / "DB" / "estoque.sqlite"
MOTIVO_AUDITORIA = "BACKFILL_BASELINE_FECHAMENTO_MES_ANTERIOR"


@dataclass(frozen=True)
class AlteracaoBaseline:
    mes_ref: str
    deposito: str
    fechamento_date: str
    qtd_nova: float
    val_novo: float
    source_file_novo: str | None
    baseline_date_antiga: str | None
    qtd_antiga: float | None
    val_antigo: float | None
    source_file_antigo: str | None
    acao: str


def _mes_seguinte(mes_ref: str) -> str:
    inicio = date.fromisoformat(f"{mes_ref}-01")
    if inicio.month == 12:
        return f"{inicio.year + 1:04d}-01"
    return f"{inicio.year:04d}-{inicio.month + 1:02d}"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _criar_tabela_auditoria(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS baseline_mensal_auditoria (
            auditoria_id INTEGER PRIMARY KEY AUTOINCREMENT,
            executado_em TEXT NOT NULL,
            motivo TEXT NOT NULL,
            acao TEXT NOT NULL,
            mes_ref TEXT NOT NULL,
            deposito TEXT NOT NULL,
            baseline_date_antiga TEXT,
            qtd_base_total_antiga REAL,
            val_base_total_antigo REAL,
            source_file_antigo TEXT,
            baseline_date_nova TEXT NOT NULL,
            qtd_base_total_nova REAL NOT NULL,
            val_base_total_novo REAL NOT NULL,
            source_file_novo TEXT
        )
        """
    )


def planejar_backfill(
    con: sqlite3.Connection,
    deposito: str,
    de_mes: str,
    ate_mes: str,
) -> list[AlteracaoBaseline]:
    """Monta o plano sem alterar o banco."""

    datas_fechamento = con.execute(
        """
        SELECT
            SUBSTR(snapshot_date, 1, 7) AS mes_snapshot,
            MAX(snapshot_date) AS fechamento_date
        FROM fact_estoque_snapshot
        WHERE deposito = ?
        GROUP BY SUBSTR(snapshot_date, 1, 7)
        ORDER BY mes_snapshot
        """,
        (deposito,),
    ).fetchall()

    alteracoes: list[AlteracaoBaseline] = []

    for mes_snapshot, fechamento_date in datas_fechamento:
        mes_destino = _mes_seguinte(str(mes_snapshot))

        # Não utiliza mês ainda aberto como se fosse fechamento oficial.
        if mes_destino < de_mes or mes_destino > ate_mes:
            continue

        totais = con.execute(
            """
            SELECT
                COALESCE(SUM(qtd_total), 0),
                COALESCE(SUM(val_total), 0)
            FROM fact_estoque_snapshot
            WHERE deposito = ?
              AND snapshot_date = ?
            """,
            (deposito, fechamento_date),
        ).fetchone()

        arquivos = con.execute(
            """
            SELECT DISTINCT source_file
            FROM fact_estoque_snapshot
            WHERE deposito = ?
              AND snapshot_date = ?
              AND source_file IS NOT NULL
              AND TRIM(source_file) <> ''
            ORDER BY source_file
            """,
            (deposito, fechamento_date),
        ).fetchall()

        source_file_novo = ",".join(
            str(linha[0]) for linha in arquivos
        ) or None

        atual = con.execute(
            """
            SELECT
                baseline_date,
                qtd_base_total,
                val_base_total,
                source_file
            FROM baseline_mensal
            WHERE mes_ref = ?
              AND deposito = ?
            """,
            (mes_destino, deposito),
        ).fetchone()

        qtd_nova = float(totais[0] or 0.0)
        val_novo = float(totais[1] or 0.0)

        if atual is None:
            data_antiga = None
            qtd_antiga = None
            val_antigo = None
            arquivo_antigo = None
            acao = "INSERIR"
        else:
            data_antiga = atual[0]
            qtd_antiga = (
                None if atual[1] is None else float(atual[1])
            )
            val_antigo = (
                None if atual[2] is None else float(atual[2])
            )
            arquivo_antigo = atual[3]

            igual = (
                data_antiga == fechamento_date
                and qtd_antiga == qtd_nova
                and val_antigo == val_novo
            )
            acao = "MANTER" if igual else "ATUALIZAR"

        alteracoes.append(
            AlteracaoBaseline(
                mes_ref=mes_destino,
                deposito=deposito,
                fechamento_date=str(fechamento_date),
                qtd_nova=qtd_nova,
                val_novo=val_novo,
                source_file_novo=source_file_novo,
                baseline_date_antiga=data_antiga,
                qtd_antiga=qtd_antiga,
                val_antigo=val_antigo,
                source_file_antigo=arquivo_antigo,
                acao=acao,
            )
        )

    return alteracoes


def exibir_plano(alteracoes: list[AlteracaoBaseline]) -> None:
    print("=" * 118)
    print("BACKFILL DO BASELINE PELO FECHAMENTO DO MÊS ANTERIOR")
    print("=" * 118)
    print(
        f"{'MÊS':<8} {'AÇÃO':<10} {'DATA ANT.':<12} "
        f"{'BASELINE ANTIGO':>20} {'DATA NOVA':<12} "
        f"{'BASELINE NOVO':>20} {'DIFERENÇA':>20}"
    )
    print("-" * 118)

    for item in alteracoes:
        antigo = item.val_antigo
        diferenca = (
            None if antigo is None else item.val_novo - antigo
        )
        print(
            f"{item.mes_ref:<8} "
            f"{item.acao:<10} "
            f"{(item.baseline_date_antiga or '-'): <12} "
            f"{(antigo if antigo is not None else 0):>20,.2f} "
            f"{item.fechamento_date:<12} "
            f"{item.val_novo:>20,.2f} "
            f"{(diferenca if diferenca is not None else 0):>20,.2f}"
        )

    print("=" * 118)
    print(
        "Resumo: "
        f"{sum(i.acao == 'INSERIR' for i in alteracoes)} inserir; "
        f"{sum(i.acao == 'ATUALIZAR' for i in alteracoes)} atualizar; "
        f"{sum(i.acao == 'MANTER' for i in alteracoes)} manter."
    )


def aplicar_backfill(
    con: sqlite3.Connection,
    alteracoes: list[AlteracaoBaseline],
) -> tuple[int, int]:
    """Aplica o plano de forma transacional e audita o antes/depois."""

    alterados = 0
    kpis_recalculados = 0
    executado_em = _agora()

    con.execute("BEGIN IMMEDIATE")

    try:
        _criar_tabela_auditoria(con)

        for item in alteracoes:
            if item.acao == "MANTER":
                continue

            con.execute(
                """
                INSERT INTO baseline_mensal_auditoria (
                    executado_em,
                    motivo,
                    acao,
                    mes_ref,
                    deposito,
                    baseline_date_antiga,
                    qtd_base_total_antiga,
                    val_base_total_antigo,
                    source_file_antigo,
                    baseline_date_nova,
                    qtd_base_total_nova,
                    val_base_total_novo,
                    source_file_novo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    executado_em,
                    MOTIVO_AUDITORIA,
                    item.acao,
                    item.mes_ref,
                    item.deposito,
                    item.baseline_date_antiga,
                    item.qtd_antiga,
                    item.val_antigo,
                    item.source_file_antigo,
                    item.fechamento_date,
                    item.qtd_nova,
                    item.val_novo,
                    item.source_file_novo,
                ),
            )

            con.execute(
                """
                INSERT INTO baseline_mensal (
                    mes_ref,
                    deposito,
                    baseline_date,
                    qtd_base_total,
                    val_base_total,
                    source_file,
                    load_ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mes_ref, deposito) DO UPDATE SET
                    baseline_date = excluded.baseline_date,
                    qtd_base_total = excluded.qtd_base_total,
                    val_base_total = excluded.val_base_total,
                    source_file = excluded.source_file,
                    load_ts = excluded.load_ts
                """,
                (
                    item.mes_ref,
                    item.deposito,
                    item.fechamento_date,
                    item.qtd_nova,
                    item.val_novo,
                    item.source_file_novo,
                    executado_em,
                ),
            )
            alterados += 1

            # Mantém a tabela técnica usada pelo Excel do ETL coerente.
            # O Giro do BI replicado no Streamlit não utiliza esta tabela.
            ultima_data_mes = con.execute(
                """
                SELECT MAX(snapshot_date)
                FROM fact_estoque_snapshot
                WHERE deposito = ?
                  AND snapshot_date LIKE ?
                """,
                (item.deposito, f"{item.mes_ref}-%"),
            ).fetchone()[0]

            if ultima_data_mes:
                meta = con.execute(
                    """
                    SELECT meta_giro
                    FROM kpi_mensal_resumo
                    WHERE mes_ref = ?
                      AND deposito = ?
                    """,
                    (item.mes_ref, item.deposito),
                ).fetchone()

                meta_giro = float(meta[0]) if meta else 1.2

                compute_and_store_kpi(
                    con,
                    item.deposito,
                    date.fromisoformat(str(ultima_data_mes)),
                    meta_giro,
                )
                kpis_recalculados += 1

        con.commit()

    except Exception:
        con.rollback()
        raise

    return alterados, kpis_recalculados


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Transfere o fechamento de cada mês para o baseline do mês "
            "seguinte. Sem --aplicar, apenas exibe a simulação."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB,
        help="Caminho do estoque.sqlite.",
    )
    parser.add_argument("--deposito", default="MAST")
    parser.add_argument("--de-mes", default="2026-02")
    parser.add_argument("--ate-mes", default="2026-10")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Confirma a gravação. Sem esta opção, não altera o banco.",
    )
    args = parser.parse_args()

    banco = args.database.resolve()
    if not banco.exists():
        raise FileNotFoundError(f"Banco não encontrado: {banco}")

    con = sqlite3.connect(str(banco))

    try:
        alteracoes = planejar_backfill(
            con,
            deposito=args.deposito,
            de_mes=args.de_mes,
            ate_mes=args.ate_mes,
        )
        exibir_plano(alteracoes)

        if not args.aplicar:
            print("SIMULAÇÃO concluída. Nenhuma alteração foi realizada.")
            return

        alterados, kpis = aplicar_backfill(con, alteracoes)
        print(
            "APLICAÇÃO concluída com sucesso: "
            f"{alterados} baseline(s) alterado(s); "
            f"{kpis} KPI(s) técnico(s) recalculado(s)."
        )

    finally:
        con.close()


if __name__ == "__main__":
    main()
