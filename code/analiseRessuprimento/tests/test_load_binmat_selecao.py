from __future__ import annotations

"""Testes da seleção do snapshot atual do BINMAT."""

import os
from pathlib import Path
import tempfile
import unittest

from etl.load_binmat import selecionar_snapshot_mais_recente


class TestSelecaoSnapshotBinmat(unittest.TestCase):
    """Protege a escolha por metadado sem depender do nome do relatório."""

    def test_seleciona_arquivo_com_modificacao_mais_recente(self) -> None:
        """Um nome alfabeticamente menor pode ser o snapshot mais novo."""

        with tempfile.TemporaryDirectory() as diretorio:
            pasta = Path(diretorio)
            antigo = pasta / "Z_BINMAT_ANTIGO.xlsx"
            recente = pasta / "A_BINMAT_RECENTE.xlsx"
            antigo.touch()
            recente.touch()

            os.utime(antigo, (1_700_000_000, 1_700_000_000))
            os.utime(recente, (1_800_000_000, 1_800_000_000))

            selecionado = selecionar_snapshot_mais_recente(pasta)

            self.assertEqual(selecionado, recente)

    def test_ignora_arquivo_temporario_do_excel(self) -> None:
        """O arquivo aberto pelo Excel nunca pode substituir o relatório."""

        with tempfile.TemporaryDirectory() as diretorio:
            pasta = Path(diretorio)
            valido = pasta / "BINMAT.xlsx"
            temporario = pasta / "~$BINMAT.xlsx"
            valido.touch()
            temporario.touch()

            os.utime(valido, (1_700_000_000, 1_700_000_000))
            os.utime(temporario, (1_800_000_000, 1_800_000_000))

            selecionado = selecionar_snapshot_mais_recente(pasta)

            self.assertEqual(selecionado, valido)

    def test_informa_ausencia_de_planilha(self) -> None:
        """A rotina falha claramente quando não existe snapshot utilizável."""

        with tempfile.TemporaryDirectory() as diretorio:
            with self.assertRaisesRegex(
                FileNotFoundError,
                "Nenhum arquivo .xlsx",
            ):
                selecionar_snapshot_mais_recente(Path(diretorio))


if __name__ == "__main__":
    unittest.main()
