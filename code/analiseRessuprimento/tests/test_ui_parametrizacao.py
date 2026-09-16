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
    from ui.parametrizacao import _obter_configuracao_decisao


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

    def test_parametrizar_solicita_min_e_max(self) -> None:
        """A opção operacional principal não exige justificativa."""

        configuracao = _obter_configuracao_decisao("Parametrizar")

        self.assertEqual(configuracao["codigo"], "PARAMETRIZAR")
        self.assertTrue(configuracao["solicita_min_max"])
        self.assertFalse(configuracao["solicita_justificativa"])

    def test_nao_parametrizar_solicita_justificativa(self) -> None:
        """Encerrar sem parâmetros exige explicar o motivo."""

        configuracao = _obter_configuracao_decisao("Não parametrizar")

        self.assertEqual(configuracao["codigo"], "NAO_PARAMETRIZAR")
        self.assertFalse(configuracao["solicita_min_max"])
        self.assertTrue(configuracao["solicita_justificativa"])

    def test_investigar_solicita_justificativa(self) -> None:
        """A investigação registra o que ainda precisa ser esclarecido."""

        configuracao = _obter_configuracao_decisao("Investigar")

        self.assertEqual(configuracao["codigo"], "INVESTIGAR")
        self.assertFalse(configuracao["solicita_min_max"])
        self.assertTrue(configuracao["solicita_justificativa"])


if __name__ == "__main__":
    unittest.main()
