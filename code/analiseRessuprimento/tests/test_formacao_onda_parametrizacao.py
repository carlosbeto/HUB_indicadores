from __future__ import annotations

import unittest

import pandas as pd

from rules.formacao_onda_parametrizacao import (
    formar_onda_por_percentual_demanda,
)


class TestFormacaoOndaParametrizacao(unittest.TestCase):

    def test_forma_menor_conjunto_que_atinge_percentual_alvo(self):
        df_backlog = pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "demanda_relevante": 40.0,
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "demanda_relevante": 30.0,
                },
                {
                    "prioridade": 3,
                    "material": "1000003",
                    "demanda_relevante": 20.0,
                },
                {
                    "prioridade": 4,
                    "material": "1000004",
                    "demanda_relevante": 10.0,
                },
            ]
        )

        df_onda, indicadores = formar_onda_por_percentual_demanda(
            df_backlog,
            percentual_alvo=50,
        )

        self.assertEqual(
            len(df_onda),
            2,
        )

        self.assertEqual(
            list(df_onda["material"]),
            [
                "1000001",
                "1000002",
            ],
        )

        self.assertEqual(
            indicadores["demanda_total_backlog"],
            100.0,
        )

        self.assertEqual(
            indicadores["demanda_total_onda"],
            70.0,
        )

        self.assertEqual(
            indicadores["percentual_real_cobertura"],
            70.0,
        )

    def test_respeita_prioridade_e_nao_ordem_fisica_dataframe(self):
        df_backlog = pd.DataFrame(
            [
                {
                    "prioridade": 3,
                    "material": "1000003",
                    "demanda_relevante": 20.0,
                },
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "demanda_relevante": 60.0,
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "demanda_relevante": 20.0,
                },
            ]
        )

        df_onda, _ = formar_onda_por_percentual_demanda(
            df_backlog,
            percentual_alvo=50,
        )

        self.assertEqual(
            len(df_onda),
            1,
        )

        self.assertEqual(
            df_onda.iloc[0]["material"],
            "1000001",
        )

    def test_percentual_100_retorna_todo_backlog(self):
        df_backlog = pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "demanda_relevante": 70.0,
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "demanda_relevante": 30.0,
                },
            ]
        )

        df_onda, indicadores = formar_onda_por_percentual_demanda(
            df_backlog,
            percentual_alvo=100,
        )

        self.assertEqual(
            len(df_onda),
            2,
        )

        self.assertEqual(
            indicadores["percentual_real_cobertura"],
            100.0,
        )

    def test_rejeita_percentual_invalido(self):
        df_backlog = pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "demanda_relevante": 10.0,
                },
            ]
        )

        for percentual in (
            0,
            -1,
            101,
        ):
            with self.subTest(
                percentual=percentual,
            ):
                with self.assertRaises(ValueError):
                    formar_onda_por_percentual_demanda(
                        df_backlog,
                        percentual_alvo=percentual,
                    )

    def test_rejeita_backlog_vazio(self):
        df_backlog = pd.DataFrame()

        with self.assertRaises(ValueError):
            formar_onda_por_percentual_demanda(
                df_backlog,
                percentual_alvo=50,
            )

    def test_rejeita_demanda_nao_positiva(self):
        df_backlog = pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "demanda_relevante": 0.0,
                },
            ]
        )

        with self.assertRaises(ValueError):
            formar_onda_por_percentual_demanda(
                df_backlog,
                percentual_alvo=50,
            )


if __name__ == "__main__":
    unittest.main()
