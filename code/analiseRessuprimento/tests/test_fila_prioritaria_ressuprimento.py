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
    preparar_fila_parametrizacao,
    preparar_fila_prioritaria,
    preparar_fila_risco_pcp,
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
                    "necessidade_operacional": float(
                        36 - prioridade
                    ),
                    "quantidade_sugerida": float(
                        36 - prioridade
                    ),
                    "status_operacional": "RESSUPRIR",
                    "prioridade_urgencia": prioridade,
                }
            )

        for indice in range(36, 41):
            linhas.append(
                {
                    "material": f"{indice:07d}",
                    "necessidade_ressuprimento": 0.0,
                    "necessidade_operacional": 0.0,
                    "quantidade_sugerida": 0.0,
                    "status_operacional": "SEM NECESSIDADE",
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

    def test_abastecedor_recebe_completo_e_parcial(self) -> None:
        """A fila física contém somente transferências que podem ocorrer."""

        radar = pd.DataFrame(
            [
                {
                    "material": "1000001",
                    "necessidade_ressuprimento": 100.0,
                    "necessidade_operacional": 100.0,
                    "quantidade_sugerida": 0.0,
                    "status_operacional": "SEM SALDO T001",
                },
                {
                    "material": "1000002",
                    "necessidade_ressuprimento": 80.0,
                    "necessidade_operacional": 80.0,
                    "quantidade_sugerida": 30.0,
                    "status_operacional": "RESSUPRIR PARCIAL",
                },
                {
                    "material": "1000003",
                    "necessidade_ressuprimento": 60.0,
                    "necessidade_operacional": 60.0,
                    "quantidade_sugerida": 60.0,
                    "status_operacional": "RESSUPRIR",
                },
            ]
        )

        fila = preparar_fila_prioritaria(
            radar,
            limite=10,
        )

        self.assertEqual(
            fila["material"].tolist(),
            ["1000002", "1000003"],
        )

    def test_pcp_recebe_risco_integral_e_residual(self) -> None:
        """O PCP enxerga falta total e o restante após ação parcial."""

        radar = pd.DataFrame(
            [
                {
                    "material": "1000001",
                    "necessidade_ressuprimento": 100.0,
                    "necessidade_operacional": 100.0,
                    "quantidade_sugerida": 0.0,
                    "status_operacional": "SEM SALDO T001",
                },
                {
                    "material": "1000002",
                    "necessidade_ressuprimento": 80.0,
                    "necessidade_operacional": 80.0,
                    "quantidade_sugerida": 30.0,
                    "status_operacional": "RESSUPRIR PARCIAL",
                },
                {
                    "material": "1000003",
                    "necessidade_ressuprimento": 60.0,
                    "necessidade_operacional": 60.0,
                    "quantidade_sugerida": 60.0,
                    "status_operacional": "RESSUPRIR",
                },
            ]
        )

        fila = preparar_fila_risco_pcp(
            radar,
            limite=10,
        )

        self.assertEqual(
            fila["material"].tolist(),
            ["1000001", "1000002"],
        )
        self.assertEqual(
            fila["quantidade_risco_pcp"].tolist(),
            [100.0, 50.0],
        )

    @staticmethod
    def _criar_radar_parametrizacao() -> pd.DataFrame:
        """Cria posições suficientes para testar a fila viva da BINMAT."""

        return pd.DataFrame(
            [
                {
                    "material": "1000001",
                    "descricao_material": "MATERIAL ALFA",
                    "posicao": "PT02-001-001-001",
                    "media_mensal_saida": 100.0,
                    "saldo_pt02_fisico": 20.0,
                    "status_parametrizacao_pt02": "PARAMETRIZADA",
                },
                {
                    "material": "1000002",
                    "descricao_material": "MATERIAL BETA",
                    "posicao": "PT02-001-002-001",
                    "media_mensal_saida": 80.0,
                    "saldo_pt02_fisico": 30.0,
                    "status_parametrizacao_pt02": "PARAMETRIZAÇÃO PENDENTE",
                },
                {
                    "material": "1000003",
                    "descricao_material": "MATERIAL GAMA",
                    "posicao": "PT02-001-003-001",
                    "media_mensal_saida": 120.0,
                    "saldo_pt02_fisico": 50.0,
                    "status_parametrizacao_pt02": (
                        "REVISAR MIN/MAX — SALDO ACIMA DO MAX"
                    ),
                },
            ]
        )

    def test_fila_parametrizacao_exclui_posicoes_regulares(self) -> None:
        """Uma posição corrigida não permanece na lista de trabalho."""

        fila = preparar_fila_parametrizacao(
            self._criar_radar_parametrizacao()
        )

        self.assertEqual(
            fila["material"].tolist(),
            ["1000003", "1000002"],
        )

    def test_fila_parametrizacao_filtra_diagnostico(self) -> None:
        """O controlador pode concentrar a atuação em uma condição."""

        fila = preparar_fila_parametrizacao(
            self._criar_radar_parametrizacao(),
            diagnosticos=["PARAMETRIZAÇÃO PENDENTE"],
        )

        self.assertEqual(fila["material"].tolist(), ["1000002"])

    def test_fila_parametrizacao_pesquisa_material_ou_posicao(self) -> None:
        """A busca textual não depende de assumir tarefas individuais."""

        radar = self._criar_radar_parametrizacao()

        por_material = preparar_fila_parametrizacao(
            radar,
            busca="1000002",
        )
        por_posicao = preparar_fila_parametrizacao(
            radar,
            busca="003-001",
        )

        self.assertEqual(por_material["material"].tolist(), ["1000002"])
        self.assertEqual(por_posicao["material"].tolist(), ["1000003"])


if __name__ == "__main__":
    unittest.main()
