"""Regressão do corte crítico, alocação por origem e exportação Excel.

Executar na raiz code/analiseRessuprimento:
python -m unittest discover -s tests -p test_criticos_ressuprimento.py -v
"""
from io import BytesIO
import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from repositories.estoque_repository import (
    carregar_saldo_t001_por_posicao, carregar_saldo_t001_por_material,
)
from services.radar_ressuprimento_service import (
    preparar_criticos_ressuprimento, preparar_retiradas_t001,
    preparar_fila_prioritaria, preparar_fila_risco_pcp,
)
from rules.ressuprimento_pt02 import calcular_radar_ressuprimento_pt02
from ui.ressuprimento_pt02 import gerar_excel_ressuprimento


def item(material="1000001", **valores):
    dados = dict(material=material, descricao_material="Produto teste", posicao="PT02-A",
        unidade_operacional="PEÇ", media_mensal_saida=10.0, media_mensal_operacional=10.0,
        saldo_pt02_f5=4.0, saldo_t001_f5=20.0, necessidade_operacional=6.0,
        quantidade_sugerida=6.0, necessidade_ressuprimento=6.0,
        demanda_comercial=60.0, demanda_tecnica=0.0, duplicidade_pt02=False, status_operacional="RESSUPRIR",
        status_saldo_pt02="F5 INFORMADO", status_parametrizacao_pt02="PARAMETRIZADA")
    dados.update(valores)
    return dados


def origem(material="1000001", posicao="T-A", saldo=20.0, unidade="PEÇ"):
    return dict(material=material, posicao_t001=posicao, saldo_origem_f5=saldo,
                unidade_medida=unidade)


class CriticosTest(unittest.TestCase):
    def test_corte_estrito_50_porcento(self):
        radar = pd.DataFrame([item("A", saldo_pt02_f5=4.99),
                              item("B", saldo_pt02_f5=5), item("C", saldo_pt02_f5=5.01)])
        self.assertEqual(preparar_criticos_ressuprimento(radar).material.tolist(), ["A"])

    def test_corte_usa_media_analitica(self):
        radar = pd.DataFrame([item(media_mensal_saida=9.2, media_mensal_operacional=10,
                                   saldo_pt02_f5=4.7)])
        self.assertTrue(preparar_criticos_ressuprimento(radar).empty)

    def test_sem_demanda_e_conflito_fora(self):
        radar = pd.DataFrame([item("A", media_mensal_saida=0, saldo_pt02_f5=-1),
                              item("B", duplicidade_pt02=True)])
        self.assertTrue(preparar_criticos_ressuprimento(radar).empty)

    def test_lista_integral_mais_de_100(self):
        radar = pd.DataFrame([item(str(i)) for i in range(130)])
        antes = radar.copy(deep=True)
        self.assertEqual(len(preparar_criticos_ressuprimento(radar)), 130)
        pd.testing.assert_frame_equal(radar, antes)

    def test_contratos_anteriores_preservados(self):
        radar = pd.DataFrame([item("A"), item("B", status_operacional="SEM SALDO T001",
                                                          quantidade_sugerida=0)])
        self.assertEqual(len(preparar_fila_prioritaria(radar, limite=1)), 1)
        risco = preparar_fila_risco_pcp(radar, limite=1)
        self.assertEqual(risco.iloc[0].quantidade_risco_pcp, 6)


class PlanoTest(unittest.TestCase):
    def plano(self, itens=None, origens=None):
        return preparar_retiradas_t001(pd.DataFrame(itens or [item()]),
                                      pd.DataFrame(origens if origens is not None else [origem()]))

    def test_completa_media_e_nao_apenas_metade(self):
        plano, pendencias = self.plano()
        self.assertEqual(plano.quantidade_retirar.sum(), 6)
        self.assertTrue(pendencias.empty)

    def test_divide_entre_origens_sem_duplicar_necessidade(self):
        plano, pendencias = self.plano(origens=[origem(posicao="T-A", saldo=2),
                                              origem(posicao="T-B", saldo=4)])
        self.assertEqual(plano.quantidade_retirar.tolist(), [2, 4])
        self.assertEqual(plano.quantidade_retirar.sum(), 6)
        self.assertTrue(pendencias.empty)

    def test_agrupa_multiplos_skus_na_mesma_origem(self):
        plano, pendencias = self.plano([item("A"), item("B")], [
            origem("A", "T-A", 10), origem("A", "T-Z", 10), origem("B", "T-Z", 10)])
        self.assertEqual(plano.posicao_t001.tolist(), ["T-Z", "T-Z"])
        self.assertTrue(pendencias.empty)

    def test_empate_escolhe_origem_que_evite_segunda_retirada(self):
        plano, pendencias = self.plano(origens=[origem(posicao="T-A", saldo=2),
                                              origem(posicao="T-B", saldo=10)])
        self.assertEqual(plano.posicao_t001.tolist(), ["T-B"])
        self.assertEqual(plano.quantidade_retirar.sum(), 6)
        self.assertTrue(pendencias.empty)

    def test_atendimento_parcial_e_residual(self):
        plano, pendencias = self.plano(
            [item(quantidade_sugerida=3, saldo_t001_f5=3)], [origem(saldo=3)])
        self.assertEqual(plano.quantidade_retirar.sum(), 3)
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 3)

    def test_sem_origem_permanece_visivel(self):
        plano, pendencias = self.plano([item(quantidade_sugerida=0, saldo_t001_f5=0)], [])
        self.assertTrue(plano.empty)
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 6)

    def test_sugestao_do_motor_e_teto(self):
        plano, pendencias = self.plano([item(quantidade_sugerida=2)], [origem(saldo=20)])
        self.assertEqual(plano.quantidade_retirar.sum(), 2)
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 4)

    def test_inteiros_arredondados_por_origem(self):
        plano, pendencias = self.plano(origens=[origem(posicao="T-A", saldo=2.8),
                                              origem(posicao="T-B", saldo=3.8)])
        self.assertEqual(plano.quantidade_retirar.tolist(), [2, 3])
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 1)

    def test_unidade_fracionavel(self):
        plano, pendencias = self.plano([item(unidade_operacional="KG", necessidade_operacional=0.75,
                    quantidade_sugerida=0.75)], [origem(saldo=0.5, unidade="KG")])
        self.assertEqual(plano.quantidade_retirar.sum(), 0.5)
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 0.25)

    def test_nao_mistura_unidades(self):
        plano, pendencias = self.plano(origens=[origem(unidade="KG")])
        self.assertTrue(plano.empty)
        self.assertIn("UMB incompatível", pendencias.iloc[0].motivo)

    def test_umb_ausente_e_origem_ambigua(self):
        plano, pendencias = self.plano([item(unidade_operacional=pd.NA)], [origem()])
        self.assertTrue(plano.empty)
        plano, pendencias = self.plano(origens=[origem(), origem(unidade="KG")])
        self.assertTrue(plano.empty)

    def test_conflito_destino_nao_e_alocado(self):
        with self.assertRaises(ValueError):
            self.plano([item(), item()], [origem()])

    def test_origem_em_processo_nao_gera_retirada(self):
        plano, pendencias = self.plano(origens=[
            origem(posicao=" embalar-etiquetar ", saldo=100),
            origem(posicao="T-A", saldo=2),
        ])
        self.assertEqual(plano.posicao_t001.tolist(), ["T-A"])
        self.assertEqual(plano.quantidade_retirar.sum(), 2)
        self.assertEqual(pendencias.iloc[0].quantidade_pendente, 4)

    def test_plano_vazio_tem_contrato(self):
        plano, pendencias = preparar_retiradas_t001(pd.DataFrame(), pd.DataFrame())
        self.assertIn("quantidade_retirar", plano.columns)
        self.assertIn("quantidade_pendente", pendencias.columns)


class RepositorioTest(unittest.TestCase):
    def test_embalar_etiquetar_excluida_do_saldo_e_das_origens(self):
        with sqlite3.connect(":memory:") as conn:
            conn.executescript("""
                CREATE TABLE dim_posicao_material (id INTEGER, material TEXT,
                    posicao TEXT, deposito TEXT, tipo_deposito TEXT);
                CREATE TABLE posicao_material_fontes (id INTEGER PRIMARY KEY,
                    id_posicao_material INTEGER, fonte TEXT, presente_atual INTEGER);
                CREATE TABLE fact_saldo_posicao (id_posicao_material INTEGER,
                    tipo_estoque TEXT, unidade_medida TEXT, quantidade_disponivel REAL);
                INSERT INTO dim_posicao_material VALUES
                    (1,'A','T001-001-001-001','1002','T001'),
                    (2,'A',' embalar-etiquetar ','1002','T001'),
                    (3,'B','EMBALAR-ETIQUETAR','1002','T001');
                INSERT INTO posicao_material_fontes VALUES
                    (1,1,'VISAO_GERAL',1),(2,2,'VISAO_GERAL',1),(3,3,'VISAO_GERAL',1),
                    (4,1,'BINMAT',1),(5,2,'BINMAT',1),(6,3,'BINMAT',1);
                INSERT INTO fact_saldo_posicao VALUES
                    (1,'F5','PEÇ',2),(2,'F5','PEÇ',100),(3,'F5','PEÇ',50),
                    (2,'B5','PEÇ',25);
            """)
            origens = carregar_saldo_t001_por_posicao(conn)
            saldos = carregar_saldo_t001_por_material(conn)
            self.assertEqual(origens.posicao_t001.tolist(), ["T001-001-001-001"])
            self.assertEqual(saldos.material.tolist(), ["A"])
            self.assertEqual(saldos.iloc[0].saldo_t001_f5, 2)
            self.assertEqual(saldos.iloc[0].saldo_t001_b5, 0)
            self.assertEqual(saldos.iloc[0].qtd_posicoes_t001, 1)


    def test_filtra_snapshot_f5_deposito_e_origem_sem_multiplicar(self):
        with sqlite3.connect(":memory:") as conn:
            conn.executescript("""
                CREATE TABLE dim_posicao_material (id INTEGER, material TEXT,
                    posicao TEXT, deposito TEXT, tipo_deposito TEXT);
                CREATE TABLE posicao_material_fontes (id_posicao_material INTEGER,
                    fonte TEXT, presente_atual INTEGER);
                CREATE TABLE fact_saldo_posicao (id_posicao_material INTEGER,
                    tipo_estoque TEXT, unidade_medida TEXT, quantidade_disponivel REAL);
                INSERT INTO dim_posicao_material VALUES
                    (1,'A','T-A','1002','T001'),(2,'A','T-B','1002','T001'),
                    (3,'A','P-A','1002','PT02'),(4,'A','T-X','9999','T001');
                INSERT INTO posicao_material_fontes VALUES
                    (1,'VISAO_GERAL',1),(1,'VISAO_GERAL',1),
                    (2,'VISAO_GERAL',0),(3,'VISAO_GERAL',1),(4,'VISAO_GERAL',1);
                INSERT INTO fact_saldo_posicao VALUES (1,'F5','PEÇ',4),(1,'B5','PEÇ',99),
                    (2,'F5','PEÇ',50),(3,'F5','PEÇ',50),(4,'F5','PEÇ',50);
            """)
            df = carregar_saldo_t001_por_posicao(conn)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0].saldo_origem_f5, 4)


class ExcelTest(unittest.TestCase):
    def test_excel_integral_numerico_seguro_e_filtravel(self):
        criticos = pd.DataFrame([item(str(i).zfill(7), descricao_material="=1+1") for i in range(130)])
        plano, pendencias = preparar_retiradas_t001(criticos, pd.DataFrame())
        dados = gerar_excel_ressuprimento(criticos, plano, pendencias, pd.DataFrame(), {
            "data_inicio_demanda": pd.Timestamp("2026-05-05"),
            "data_referencia_demanda": pd.Timestamp("2026-11-05")})
        wb = load_workbook(BytesIO(dados))
        self.assertEqual(len(wb.sheetnames), 5)
        ws = wb["Criticos"]
        self.assertEqual(ws.max_row, 131)
        self.assertEqual(ws["A2"].value, "0000000")
        self.assertEqual(ws["B2"].data_type, "s")
        self.assertEqual(ws["B2"].value, "=1+1")
        self.assertIsInstance(ws["D2"].value, (int, float))
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertTrue(ws.auto_filter.ref)
        self.assertEqual(wb["Retiradas por origem"].max_row, 1)


class IntegracaoRadarTest(unittest.TestCase):
    def test_motor_preservado_critico_filtrado_e_sugestao_completa(self):
        posicoes = pd.DataFrame([
            dict(material="A", posicao="PT02-A", quantidade_minima=1,
                 quantidade_maxima=30, unidade_medida="PEÇ"),
            dict(material="B", posicao="PT02-B", quantidade_minima=1,
                 quantidade_maxima=30, unidade_medida="PEÇ"),
        ])
        saldos = pd.DataFrame([
            dict(material="A", posicao="PT02-A", tipo_estoque="F5", quantidade_disponivel=4),
            dict(material="B", posicao="PT02-B", tipo_estoque="F5", quantidade_disponivel=5),
        ])
        t001 = pd.DataFrame([dict(material=m, qtd_posicoes_t001=1,
            qtd_posicoes_t001_binmat=1, saldo_t001_f5=20, saldo_t001_b5=0) for m in ["A", "B"]])
        demanda = pd.DataFrame([dict(material=m, qtd_601=60, qtd_602=0, qtd_z17=0,
            qtd_z18=0, demanda_comercial=60, demanda_tecnica=0, demanda_relevante=60)
            for m in ["A", "B"]])
        with patch("rules.ressuprimento_pt02.carregar_pt02_atuais_binmat", return_value=posicoes), \
             patch("rules.ressuprimento_pt02.carregar_saldo_pt02_atual", return_value=saldos), \
             patch("rules.ressuprimento_pt02.carregar_saldo_t001_por_material", return_value=t001), \
             patch("rules.ressuprimento_pt02.carregar_demanda_material", return_value=(
                 demanda, pd.Timestamp("2026-05-05"), pd.Timestamp("2026-11-05"))):
            radar, _ = calcular_radar_ressuprimento_pt02(sqlite3.connect(":memory:"))
        self.assertEqual(len(radar), 2)  # O radar geral continua atendendo PCM e BINMAT.
        criticos = preparar_criticos_ressuprimento(radar)
        self.assertEqual(criticos.material.tolist(), ["A"])
        self.assertEqual(criticos.iloc[0].quantidade_sugerida, 6)


class InterfaceTest(unittest.TestCase):
    def test_tela_vazia_busca_e_retorno_lista(self):
        from unittest.mock import MagicMock
        from ui import ressuprimento_pt02 as tela
        radar = pd.DataFrame([item()])
        indicadores = dict(data_inicio_demanda=pd.Timestamp("2026-05-05"),
            data_referencia_demanda=pd.Timestamp("2026-11-05"), pt02_definitivas=1)
        for codigo in ["", "1000001", "NAO EXISTE"]:
            with self.subTest(codigo=codigo), patch.object(tela, "st") as st, \
                 patch.object(tela, "calcular_radar_ressuprimento_pt02", return_value=(radar, indicadores)), \
                 patch.object(tela, "carregar_saldo_t001_por_posicao", return_value=pd.DataFrame([origem()])):
                st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
                st.text_input.return_value = codigo
                st.dataframe.return_value.selection.rows = []
                tela.render_ressuprimento_pt02(None, usuario={"nome":"Teste", "matricula":"AA000000"})
                st.slider.assert_not_called()
                st.download_button.assert_called_once()


if __name__ == "__main__":
    unittest.main()
