from __future__ import annotations

"""Testes da apresentação da fila dinâmica de parametrização BINMAT."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

with patch.dict("sys.modules", {"streamlit": MagicMock()}):
    from ui.parametrizacao import (
        ORIENTACOES_DIAGNOSTICO,
        _formatar_fila_parametrizacao,
        _gerar_csv_parametrizacao,
    )


class TestUiParametrizacao(unittest.TestCase):
    """Protege a leitura e a exportação sem depender do Streamlit aberto."""

    @staticmethod
    def _criar_fila() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "material": "2640092",
                    "descricao_material": "CONVERSOR",
                    "posicao": "PT02-002-093-001",
                    "media_mensal_operacional": 441.0,
                    "quantidade_minima": 1.0,
                    "quantidade_maxima": 10.0,
                    "lote_teorico_reposicao": 9.0,
                    "ciclos_estimados_mes": 49.0,
                    "intervalo_estimado_dias_uteis": 0.448979,
                    "saldo_pt02_f5": 52.0,
                    "saldo_pt02_b5": 0.0,
                    "saldo_pt02_fisico": 52.0,
                    "unidade_operacional": "PEÇ",
                    "classificacao_frequencia_reposicao": (
                        "EXCESSIVA — MAIS DE 22 CICLOS/MÊS"
                    ),
                    "status_parametrizacao_pt02": (
                        "REVISAR MIN/MAX — SALDO ACIMA DO MAX"
                    ),
                }
            ]
        )

    def test_formata_quantidades_discretas_sem_fracao(self) -> None:
        """A lista do controlador usa quantidades físicas inteiras."""

        exibicao = _formatar_fila_parametrizacao(self._criar_fila())

        self.assertEqual(exibicao.iloc[0]["Consumo médio/mês"], "441")
        self.assertEqual(exibicao.iloc[0]["Qtd. por reposição"], "9")
        self.assertEqual(
            exibicao.iloc[0]["Reposições estimadas/mês"],
            "49,00",
        )
        self.assertEqual(
            exibicao.iloc[0]["Dias úteis entre reposições"],
            "0,45",
        )
        self.assertEqual(exibicao.iloc[0]["Ocupação atual PT02"], "52")

    def test_csv_usa_separador_compativel_com_excel_pt_br(self) -> None:
        """A exportação contém cabeçalho UTF-8 e separador ponto e vírgula."""

        conteudo = _gerar_csv_parametrizacao(
            self._criar_fila()
        ).decode("utf-8-sig")

        self.assertIn("Material;Descrição;Posição PT02", conteudo)
        self.assertIn("2640092;CONVERSOR;PT02-002-093-001", conteudo)

    def test_csv_exporta_unidade_discreta_sem_fracao(self) -> None:
        """Quantidades em peça mantêm no CSV a mesma leitura da tela."""

        conteudo = _gerar_csv_parametrizacao(
            self._criar_fila()
        ).decode("utf-8-sig")
        linha = conteudo.splitlines()[1].split(";")

        self.assertEqual(linha[3], "441")
        self.assertEqual(linha[4], "1")
        self.assertEqual(linha[5], "10")
        self.assertEqual(linha[6], "9")
        self.assertEqual(linha[7], "49,00")
        self.assertEqual(linha[8], "0,45")
        self.assertEqual(linha[11], "52")

    def test_csv_preserva_fracao_em_unidade_fracionavel(self) -> None:
        """Grandezas fracionáveis continuam com duas casas no CSV."""

        fila = self._criar_fila()
        fila.loc[0, "unidade_operacional"] = "G"
        fila.loc[0, "media_mensal_operacional"] = 441.25
        fila.loc[0, "saldo_pt02_fisico"] = 52.5

        conteudo = _gerar_csv_parametrizacao(fila).decode("utf-8-sig")
        linha = conteudo.splitlines()[1].split(";")

        self.assertEqual(linha[3], "441,25")
        self.assertEqual(linha[11], "52,50")

    def test_cada_alerta_de_frequencia_possui_orientacao(self) -> None:
        """A tela explica a ação esperada nos três níveis de frequência."""

        for diagnostico in [
            "REVISAR MIN/MAX — REPOSIÇÃO EXCESSIVA",
            "REVISAR MIN/MAX — ALTA FREQUÊNCIA",
            "AVALIAR DIMENSIONAMENTO — REPOSIÇÃO RECORRENTE",
        ]:
            self.assertIn(diagnostico, ORIENTACOES_DIAGNOSTICO)
            self.assertTrue(ORIENTACOES_DIAGNOSTICO[diagnostico])


if __name__ == "__main__":
    unittest.main()
