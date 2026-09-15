from __future__ import annotations

"""Testes das formatações usadas no radar preventivo PT02."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# O ambiente de testes da regra não precisa instalar nem iniciar o servidor
# Streamlit. A simulação permite importar a página e exercitar somente suas
# funções puras de formatação.
with patch.dict(
    "sys.modules",
    {"streamlit": MagicMock()},
):
    from ui.ressuprimento_pt02 import (
        _formatar_numero_br,
        _formatar_numero_operacional_br,
        _formatar_quantidade,
        _formatar_quantidade_operacional,
    )


class TestUiRessuprimentoPt02(unittest.TestCase):
    """Protege a legibilidade sem alterar os valores dos cálculos."""

    def test_formata_numero_no_padrao_brasileiro(self) -> None:
        """Milhar usa ponto e decimal usa vírgula, com duas casas."""

        self.assertEqual(
            _formatar_numero_br(4432.5),
            "4.432,50",
        )

    def test_quantidade_acrescenta_umb_do_material(self) -> None:
        """A unidade acompanha a quantidade apenas na apresentação."""

        self.assertEqual(
            _formatar_quantidade(375.5, "PEÇ"),
            "375,50 PEÇ",
        )

    def test_valor_ausente_permanece_explicito(self) -> None:
        """Ausência de dado não pode ser apresentada como zero."""

        self.assertEqual(
            _formatar_numero_br(pd.NA),
            "Não informado",
        )

    def test_unidade_discreta_e_exibida_sem_casas_decimais(self) -> None:
        """A quantidade física de PEÇ não apresenta fração na tela."""

        self.assertEqual(
            _formatar_numero_operacional_br(4057.0, "PEÇ"),
            "4.057",
        )
        self.assertEqual(
            _formatar_quantidade_operacional(376.0, "PEÇ"),
            "376 PEÇ",
        )

    def test_unidade_fracionavel_mantem_duas_casas(self) -> None:
        """Grandezas fracionáveis preservam decimais na apresentação."""

        self.assertEqual(
            _formatar_quantidade_operacional(6.5, "G"),
            "6,50 G",
        )


if __name__ == "__main__":
    unittest.main()
