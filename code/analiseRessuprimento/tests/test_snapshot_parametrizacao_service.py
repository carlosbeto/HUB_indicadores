from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from services.snapshot_parametrizacao_service import (
    compor_snapshot_fisico_onda,
)


class TestSnapshotParametrizacaoService(unittest.TestCase):

    def _criar_onda_base(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                    "demanda_relevante": 100.0,
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "posicao": "PT02-001-001-002",
                    "demanda_relevante": 80.0,
                },
                {
                    "prioridade": 3,
                    "material": "1000003",
                    "posicao": "PT02-001-001-003",
                    "demanda_relevante": 60.0,
                },
                {
                    "prioridade": 4,
                    "material": "1000004",
                    "posicao": "PT02-001-001-004",
                    "demanda_relevante": 40.0,
                },
            ]
        )

    def _criar_saldo_pt02(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "id_posicao_material": 1,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                    "tipo_estoque": "F5",
                    "denominacao_tipo_estoque": "Livre",
                    "quantidade": 10.0,
                    "quantidade_entrada": 0.0,
                    "quantidade_saida": 0.0,
                    "quantidade_disponivel": 10.0,
                    "unidade_medida": "PEÇ",
                    "arquivo_origem": "teste.xlsx",
                },
                {
                    "id_posicao_material": 2,
                    "material": "1000002",
                    "posicao": "PT02-001-001-002",
                    "tipo_estoque": "F5",
                    "denominacao_tipo_estoque": "Livre",
                    "quantidade": 20.0,
                    "quantidade_entrada": 0.0,
                    "quantidade_saida": 0.0,
                    "quantidade_disponivel": 20.0,
                    "unidade_medida": "PEÇ",
                    "arquivo_origem": "teste.xlsx",
                },
                {
                    "id_posicao_material": 3,
                    "material": "1000004",
                    "posicao": "PT02-001-001-004",
                    "tipo_estoque": "B5",
                    "denominacao_tipo_estoque": "Bloqueado",
                    "quantidade": 15.0,
                    "quantidade_entrada": 0.0,
                    "quantidade_saida": 0.0,
                    "quantidade_disponivel": 15.0,
                    "unidade_medida": "PEÇ",
                    "arquivo_origem": "teste.xlsx",
                },
            ]
        )

    def _criar_saldo_t001(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "material": "1000001",
                    "qtd_posicoes_t001": 2,
                    "qtd_posicoes_t001_binmat": 1,
                    "saldo_t001_f5": 50.0,
                    "saldo_t001_b5": 0.0,
                },
                {
                    "material": "1000003",
                    "qtd_posicoes_t001": 3,
                    "qtd_posicoes_t001_binmat": 2,
                    "saldo_t001_f5": 30.0,
                    "saldo_t001_b5": 5.0,
                },
            ]
        )

    @patch(
        "services.snapshot_parametrizacao_service."
        "carregar_saldo_t001_por_material"
    )
    @patch(
        "services.snapshot_parametrizacao_service."
        "carregar_saldo_pt02_atual"
    )
    def test_compoe_snapshot_e_classifica_contexto_fisico(
        self,
        mock_pt02,
        mock_t001,
    ):
        mock_pt02.return_value = self._criar_saldo_pt02()
        mock_t001.return_value = self._criar_saldo_t001()

        df_onda = self._criar_onda_base()

        df_snapshot, indicadores = compor_snapshot_fisico_onda(
            conn=object(),
            df_onda=df_onda,
        )

        self.assertEqual(
            list(df_snapshot["material"]),
            [
                "1000001",
                "1000002",
                "1000003",
                "1000004",
            ],
        )

        self.assertEqual(
            indicadores["qtd_materiais"],
            4,
        )

        self.assertEqual(
            indicadores["pt02_saldo_identificado"],
            3,
        )

        self.assertEqual(
            indicadores["pt02_saldo_nao_identificado"],
            1,
        )

        self.assertEqual(
            indicadores["pt02_f5_positivo"],
            2,
        )

        self.assertEqual(
            indicadores["pt02_b5_positivo"],
            1,
        )

        self.assertEqual(
            indicadores["t001_f5_positivo"],
            2,
        )

        self.assertEqual(
            indicadores["t001_b5_positivo"],
            1,
        )

        material_1 = df_snapshot.loc[
            df_snapshot["material"] == "1000001"
        ].iloc[0]

        self.assertEqual(
            material_1["situacao_fisica"],
            "PT02 COM F5 + T001 COM F5",
        )

        material_2 = df_snapshot.loc[
            df_snapshot["material"] == "1000002"
        ].iloc[0]

        self.assertEqual(
            material_2["situacao_fisica"],
            "PT02 COM F5 + SEM T001 F5",
        )

        material_3 = df_snapshot.loc[
            df_snapshot["material"] == "1000003"
        ].iloc[0]

        self.assertFalse(
            material_3["saldo_pt02_identificado"]
        )

        self.assertTrue(
            pd.isna(
                material_3["saldo_pt02_f5"]
            )
        )

        self.assertEqual(
            material_3["saldo_t001_f5"],
            30.0,
        )

        self.assertEqual(
            material_3["situacao_fisica"],
            "PT02 NÃO IDENTIFICADO + T001 COM F5",
        )

        material_4 = df_snapshot.loc[
            df_snapshot["material"] == "1000004"
        ].iloc[0]

        self.assertTrue(
            material_4["saldo_pt02_identificado"]
        )

        self.assertEqual(
            material_4["saldo_pt02_f5"],
            0.0,
        )

        self.assertEqual(
            material_4["saldo_pt02_b5"],
            15.0,
        )

        self.assertEqual(
            material_4["situacao_fisica"],
            "PT02 F5 ZERO + SEM T001 F5",
        )

    @patch(
        "services.snapshot_parametrizacao_service."
        "carregar_saldo_t001_por_material"
    )
    @patch(
        "services.snapshot_parametrizacao_service."
        "carregar_saldo_pt02_atual"
    )
    def test_preserva_ordem_de_prioridade(
        self,
        mock_pt02,
        mock_t001,
    ):
        mock_pt02.return_value = pd.DataFrame()
        mock_t001.return_value = pd.DataFrame(
            columns=[
                "material",
                "qtd_posicoes_t001",
                "qtd_posicoes_t001_binmat",
                "saldo_t001_f5",
                "saldo_t001_b5",
            ]
        )

        df_onda = pd.DataFrame(
            [
                {
                    "prioridade": 3,
                    "material": "1000003",
                    "posicao": "PT02-001-001-003",
                },
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                },
                {
                    "prioridade": 2,
                    "material": "1000002",
                    "posicao": "PT02-001-001-002",
                },
            ]
        )

        df_snapshot, _ = compor_snapshot_fisico_onda(
            conn=object(),
            df_onda=df_onda,
        )

        self.assertEqual(
            list(df_snapshot["prioridade"]),
            [
                1,
                2,
                3,
            ],
        )

    def test_rejeita_onda_vazia(self):
        with self.assertRaises(ValueError):
            compor_snapshot_fisico_onda(
                conn=object(),
                df_onda=pd.DataFrame(),
            )

    def test_rejeita_material_posicao_duplicado(self):
        df_onda = pd.DataFrame(
            [
                {
                    "prioridade": 1,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                },
                {
                    "prioridade": 2,
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                },
            ]
        )

        with self.assertRaises(ValueError):
            compor_snapshot_fisico_onda(
                conn=object(),
                df_onda=df_onda,
            )


if __name__ == "__main__":
    unittest.main()
