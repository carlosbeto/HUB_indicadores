from __future__ import annotations

"""Testes das ações apresentadas pela tela de parametrização PT02."""

import unittest
from unittest.mock import MagicMock, patch

# A decisão de mostrar os botões é uma função pura e não requer um servidor
# Streamlit. A simulação permite importar a página no ambiente de testes.
with patch.dict(
    "sys.modules",
    {"streamlit": MagicMock()},
):
    from ui.parametrizacao import _obter_acoes_tarefa


class TestUiParametrizacao(unittest.TestCase):
    """Protege a visibilidade dos primeiros comandos do workflow."""

    def test_item_disponivel_em_plano_ativo_pode_ser_assumido(self) -> None:
        """Uma tarefa livre apresenta somente a ação de assumir."""

        acoes = _obter_acoes_tarefa(
            status_plano="ATIVO",
            status_item="DISPONIVEL",
            controlador_responsavel=None,
            matricula_usuario="CA049341",
        )

        self.assertEqual(acoes, {"assumir": True, "liberar": False})

    def test_responsavel_pode_liberar_tarefa_em_analise(self) -> None:
        """Somente a matrícula responsável recebe o botão de liberar."""

        acoes = _obter_acoes_tarefa(
            status_plano="ATIVO",
            status_item="EM_ANALISE",
            controlador_responsavel="CA049341",
            matricula_usuario="CA049341",
        )

        self.assertEqual(acoes, {"assumir": False, "liberar": True})

    def test_outro_controlador_nao_pode_liberar_tarefa(self) -> None:
        """Uma tarefa alheia fica visível, mas sem comandos de alteração."""

        acoes = _obter_acoes_tarefa(
            status_plano="ATIVO",
            status_item="EM_ANALISE",
            controlador_responsavel="AB123456",
            matricula_usuario="CA049341",
        )

        self.assertEqual(acoes, {"assumir": False, "liberar": False})

    def test_plano_inativo_nao_apresenta_comandos(self) -> None:
        """Nenhuma tarefa pode mudar enquanto o plano não estiver ativo."""

        acoes = _obter_acoes_tarefa(
            status_plano="RASCUNHO",
            status_item="DISPONIVEL",
            controlador_responsavel=None,
            matricula_usuario="CA049341",
        )

        self.assertEqual(acoes, {"assumir": False, "liberar": False})


if __name__ == "__main__":
    unittest.main()
