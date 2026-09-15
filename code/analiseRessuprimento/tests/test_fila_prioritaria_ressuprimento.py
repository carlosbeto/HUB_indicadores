from __future__ import annotations

# ============================================================
# TESTES DA FILA PRIORITÁRIA DO RADAR
# ============================================================
# Estes testes protegem a preparação dos dados que serão entregues à página
# Streamlit. A regra de cálculo decide a ordem; este serviço apenas remove os
# itens sem necessidade e aplica o limite escolhido pelo controlador.
# ============================================================

import unittest

import pandas as pd

from services.radar_ressuprimento_service import (
    preparar_fila_prioritaria,
)


class TestFilaPrioritariaRessuprimento(unittest.TestCase):
    """Valida o recorte Top N sem depender da interface Streamlit."""

    @staticmethod
    def _criar_radar() -> pd.DataFrame:
        """Cria 35 urgências ordenadas e 5 itens sem necessidade."""

        linhas = []

        for prioridade in range(1, 36):
            linhas.append(
                {
                    "material": f"{prioridade:07d}",
                    "necessidade_ressuprimento": float(
                        36 - prioridade
                    ),
                    "prioridade_urgencia": prioridade,
                }
            )

        for indice in range(36, 41):
            linhas.append(
                {
                    "material": f"{indice:07d}",
                    "necessidade_ressuprimento": 0.0,
                    "prioridade_urgencia": pd.NA,
                }
            )

        return pd.DataFrame(linhas)

    def test_retorna_top_vinte_urgencias(self) -> None:
        """O limite escolhido controla o tamanho da lista de ação."""

        fila = preparar_fila_prioritaria(
            self._criar_radar(),
            limite=20,
        )

        self.assertEqual(len(fila), 20)
        self.assertEqual(fila.iloc[0]["prioridade_urgencia"], 1)
        self.assertEqual(fila.iloc[-1]["prioridade_urgencia"], 20)
        self.assertTrue(
            (fila["necessidade_ressuprimento"] > 0).all()
        )

    def test_alterar_limite_nao_recalcula_prioridade(self) -> None:
        """Top 10 e Top 30 preservam a mesma ordem do motor do radar."""

        radar = self._criar_radar()

        top_dez = preparar_fila_prioritaria(
            radar,
            limite=10,
        )
        top_trinta = preparar_fila_prioritaria(
            radar,
            limite=30,
        )

        self.assertEqual(len(top_dez), 10)
        self.assertEqual(len(top_trinta), 30)
        self.assertEqual(
            top_dez["material"].tolist(),
            top_trinta.head(10)["material"].tolist(),
        )

    def test_rejeita_limite_invalido(self) -> None:
        """Um limite zero ou negativo representa erro de programação."""

        with self.assertRaisesRegex(
            ValueError,
            "maior que zero",
        ):
            preparar_fila_prioritaria(
                self._criar_radar(),
                limite=0,
            )


if __name__ == "__main__":
    unittest.main()
