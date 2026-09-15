from __future__ import annotations

# ============================================================
# TESTES DA JANELA MÓVEL DE DEMANDA
# ============================================================
#
# A média mensal não usa um semestre fixo do calendário. O repository ancora
# a análise na maior data efetivamente presente na MB51 e retrocede seis
# meses. Quando um relatório mais recente é carregado, as duas extremidades
# da janela avançam.
# ============================================================

from datetime import date
import sqlite3
import unittest

from repositories.demanda_repository import (
    calcular_data_inicio,
    carregar_demanda_material,
    obter_data_referencia,
)


class TestDemandaRepository(unittest.TestCase):
    """Protege a relação entre atualização da MB51 e janela analisada."""

    def setUp(self) -> None:
        """Cria apenas as colunas da MB51 utilizadas pela consulta."""

        self.conn = sqlite3.connect(":memory:")

        self.conn.execute(
            """
            CREATE TABLE fact_mb51_movimentos (
                material TEXT NOT NULL,
                tipo_movimento TEXT NOT NULL,
                debito_credito TEXT NOT NULL,
                quantidade REAL NOT NULL,
                data_lancamento TEXT NOT NULL
            )
            """
        )

    def tearDown(self) -> None:
        """Descarta integralmente o banco temporário de cada teste."""

        self.conn.close()

    def test_data_referencia_e_a_maior_data_carregada(self) -> None:
        """O relógio do computador não define o fim da análise."""

        self.conn.executemany(
            """
            INSERT INTO fact_mb51_movimentos (
                material,
                tipo_movimento,
                debito_credito,
                quantidade,
                data_lancamento
            )
            VALUES (?, '601', 'H', ?, ?)
            """,
            [
                ("1000001", -10.0, "2026-09-10"),
                ("1000001", -20.0, "2026-09-14"),
            ],
        )

        # Mesmo que o teste seja executado em outra data, a referência deve
        # ser a última data que veio no relatório carregado.
        self.assertEqual(
            obter_data_referencia(self.conn),
            date(2026, 9, 14),
        )

    def test_inicio_avanca_quando_a_referencia_avanca(self) -> None:
        """Demonstra diretamente que sexta e segunda têm janelas distintas."""

        self.assertEqual(
            calcular_data_inicio(
                date(2026, 9, 11),
                meses=6,
            ),
            date(2026, 3, 11),
        )

        self.assertEqual(
            calcular_data_inicio(
                date(2026, 9, 14),
                meses=6,
            ),
            date(2026, 3, 14),
        )

    def test_nova_carga_recalcula_o_conteudo_da_janela(self) -> None:
        """Comprova que movimentos antigos saem quando a janela avança."""

        # Primeira fotografia: o relatório termina em 11/09. O movimento de
        # 11/03 está exatamente no início da janela e deve participar.
        self.conn.executemany(
            """
            INSERT INTO fact_mb51_movimentos (
                material,
                tipo_movimento,
                debito_credito,
                quantidade,
                data_lancamento
            )
            VALUES (?, '601', 'H', ?, ?)
            """,
            [
                ("1000001", -60.0, "2026-03-11"),
                ("1000001", -6.0, "2026-09-11"),
            ],
        )

        primeira_demanda, primeiro_inicio, primeira_referencia = (
            carregar_demanda_material(
                self.conn,
                meses=6,
            )
        )

        self.assertEqual(primeiro_inicio, date(2026, 3, 11))
        self.assertEqual(primeira_referencia, date(2026, 9, 11))
        self.assertEqual(
            primeira_demanda.iloc[0]["demanda_relevante"],
            66.0,
        )

        # Segunda fotografia: uma nova carga acrescenta movimento em 14/09.
        # A referência passa para 14/09 e o início para 14/03. Com isso, o
        # movimento de 11/03 deixa de pertencer aos últimos seis meses.
        self.conn.execute(
            """
            INSERT INTO fact_mb51_movimentos (
                material,
                tipo_movimento,
                debito_credito,
                quantidade,
                data_lancamento
            )
            VALUES ('1000001', '601', 'H', -12.0, '2026-09-14')
            """
        )

        segunda_demanda, segundo_inicio, segunda_referencia = (
            carregar_demanda_material(
                self.conn,
                meses=6,
            )
        )

        self.assertEqual(segundo_inicio, date(2026, 3, 14))
        self.assertEqual(segunda_referencia, date(2026, 9, 14))
        self.assertEqual(
            segunda_demanda.iloc[0]["demanda_relevante"],
            18.0,
        )


if __name__ == "__main__":
    unittest.main()
