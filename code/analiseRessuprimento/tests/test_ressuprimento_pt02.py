from __future__ import annotations

# ============================================================
# TESTES DA REGRA DE RESSUPRIMENTO PT02
# ============================================================
# Versão de entrega: 2026-09-14, incluindo saldos F5 inferidos.
#
# Este arquivo não testa a aparência do Streamlit. Ele testa o motor que
# deverá produzir os dados apresentados na tela.
#
# A técnica utilizada é TDD:
#
# 1. descrevemos primeiro, por meio dos testes, o resultado esperado;
# 2. executamos os testes contra a regra atual e observamos as falhas;
# 3. somente depois alteramos a regra de produção;
# 4. os mesmos testes devem passar sem serem flexibilizados.
#
# Os DataFrames abaixo simulam as quatro fontes reais:
#
# - BINMAT: posição PT02 e parâmetros MIN/MAX;
# - VISAO_GERAL PT02: saldo atual do picking;
# - VISAO_GERAL T001: saldo disponível nas posições de excesso;
# - MB51: demanda líquida comercial e técnica.
#
# Isso permite compreender a regra com números pequenos antes de aplicá-la
# aos milhares de registros existentes no banco operacional.
# ============================================================

from datetime import date
import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

from rules.ressuprimento_pt02 import (
    calcular_radar_ressuprimento_pt02,
)


class TestRessuprimentoPt02(unittest.TestCase):
    """Protege a regra operacional de abastecimento do picking PT02.

    Os números utilizados nos testes são deliberadamente pequenos. Dessa
    forma, a regra pode ser conferida manualmente sem depender do código:
    demanda semestral de 60 unidades representa média mensal de 10 unidades.
    """

    def setUp(self) -> None:
        """Cria uma conexão apenas para respeitar o contrato da função.

        As leituras de banco são substituídas por DataFrames controlados em
        cada teste. Assim, uma falha indica problema na regra de cálculo, e
        não em arquivos externos ou no banco operacional.
        """

        # ":memory:" cria um SQLite temporário apenas na memória. Ele deixa
        # de existir quando a conexão é fechada e, portanto, nunca altera o
        # arquivo data_db\ressuprimento.sqlite.
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self) -> None:
        """Fecha a conexão isolada ao final de cada teste."""

        self.conn.close()

    # ========================================================
    # FÁBRICAS DE DADOS CONTROLADOS
    # ========================================================
    # Cada método a seguir representa uma fonte do aplicativo. Os parâmetros
    # permitem alterar somente o dado relevante para cada cenário, mantendo
    # todo o restante constante e fácil de comparar.

    @staticmethod
    def _criar_posicao(
        *,
        material: str = "1000001",
        posicao: str = "PT02-001-001-001",
        minimo: float = 0.0,
        maximo: float = 0.0,
    ) -> pd.DataFrame:
        """Monta uma posição PT02 equivalente à leitura atual da BINMAT."""

        # Uma linha representa a relação entre um material e uma posição
        # específica do picking PT02.
        return pd.DataFrame(
            [
                {
                    "id_posicao_material": 1,
                    "material": material,
                    "descricao_material": "MATERIAL DE TESTE",
                    "deposito": "1002",
                    "tipo_deposito": "PT02",
                    "posicao": posicao,
                    "quantidade_minima": minimo,
                    "quantidade_maxima": maximo,
                    "unidade_medida": "PC",
                    "data_modificacao": None,
                    "momento_criacao": None,
                    "autor": None,
                }
            ]
        )

    @staticmethod
    def _criar_saldo_pt02(
        *,
        material: str = "1000001",
        posicao: str = "PT02-001-001-001",
        saldo_f5: float = 4.0,
        saldo_b5: float = 0.0,
    ) -> pd.DataFrame:
        """Monta a fotografia F5/B5 do picking para o cenário testado."""

        # F5 e B5 permanecem em linhas separadas porque possuem significados
        # operacionais diferentes: somente F5 está livre para movimentação.
        return pd.DataFrame(
            [
                {
                    "material": material,
                    "posicao": posicao,
                    "tipo_estoque": "F5",
                    "quantidade_disponivel": saldo_f5,
                },
                {
                    "material": material,
                    "posicao": posicao,
                    "tipo_estoque": "B5",
                    "quantidade_disponivel": saldo_b5,
                },
            ]
        )

    @staticmethod
    def _criar_saldo_t001(
        *,
        material: str = "1000001",
        saldo_f5: float = 20.0,
        saldo_b5: float = 0.0,
        qtd_posicoes: int = 1,
        qtd_parametrizadas: int = 1,
    ) -> pd.DataFrame:
        """Monta o saldo agregado das posições de excesso T001."""

        # O repository real soma todas as posições T001 do material antes de
        # entregar os dados à regra. Por isso o teste já fornece o total
        # agregado e também a quantidade de posições encontradas.
        return pd.DataFrame(
            [
                {
                    "material": material,
                    "qtd_posicoes_t001": qtd_posicoes,
                    "qtd_posicoes_t001_binmat": qtd_parametrizadas,
                    "saldo_t001_f5": saldo_f5,
                    "saldo_t001_b5": saldo_b5,
                }
            ]
        )

    @staticmethod
    def _criar_demanda(
        *,
        material: str = "1000001",
        comercial: float = 48.0,
        tecnica: float = 12.0,
        umb: str | None = "PEÇ",
        quantidade_umb_distintas: int = 1,
        status_umb: str = "UMB CONSISTENTE",
    ) -> pd.DataFrame:
        """Monta a demanda líquida mantendo comercial e técnica separadas."""

        # Mantemos comercial e técnica em colunas diferentes. A coluna
        # demanda_relevante representa a soma física que saiu do estoque.
        return pd.DataFrame(
            [
                {
                    "material": material,
                    "qtd_601": comercial,
                    "qtd_602": 0.0,
                    "qtd_z17": tecnica,
                    "qtd_z18": 0.0,
                    "demanda_comercial": comercial,
                    "demanda_tecnica": tecnica,
                    "demanda_relevante": comercial + tecnica,
                    "unidade_medida_basica": umb,
                    "quantidade_umb_distintas": quantidade_umb_distintas,
                    "status_umb": status_umb,
                }
            ]
        )

    def _calcular(
        self,
        *,
        posicoes: pd.DataFrame | None = None,
        saldo_pt02: pd.DataFrame | None = None,
        saldo_t001: pd.DataFrame | None = None,
        demanda: pd.DataFrame | None = None,
        meses: int = 6,
    ) -> tuple[pd.DataFrame, dict]:
        """Executa a regra substituindo somente as quatro fontes de leitura."""

        # Quando o teste não informa uma fonte específica, usamos o cenário
        # padrão: demanda 60, saldo PT02 4 e saldo T001 20.
        posicoes = (
            self._criar_posicao()
            if posicoes is None
            else posicoes
        )
        saldo_pt02 = (
            self._criar_saldo_pt02()
            if saldo_pt02 is None
            else saldo_pt02
        )
        saldo_t001 = (
            self._criar_saldo_t001()
            if saldo_t001 is None
            else saldo_t001
        )
        demanda = (
            self._criar_demanda()
            if demanda is None
            else demanda
        )

        # patch substitui temporariamente as funções que consultariam o banco.
        # Ao sair deste bloco, as funções originais são restauradas. Assim, os
        # testes exercitam a regra real sem depender dos relatórios reais.
        with (
            patch(
                "rules.ressuprimento_pt02.carregar_pt02_atuais_binmat",
                return_value=posicoes,
            ),
            patch(
                "rules.ressuprimento_pt02.carregar_saldo_pt02_atual",
                return_value=saldo_pt02,
            ),
            patch(
                "rules.ressuprimento_pt02.carregar_saldo_t001_por_material",
                return_value=saldo_t001,
            ),
            patch(
                "rules.ressuprimento_pt02.carregar_demanda_material",
                return_value=(
                    demanda,
                    date(2026, 3, 10),
                    date(2026, 9, 10),
                ),
            ),
        ):
            # Esta é a mesma função que será utilizada posteriormente pela
            # página principal do Streamlit.
            return calcular_radar_ressuprimento_pt02(
                self.conn,
                meses=meses,
            )

    def test_media_mensal_e_demanda_semestral_dividida_por_seis(
        self,
    ) -> None:
        """Comprova diretamente o cálculo 60 unidades / 6 meses = 10."""

        # Cenário padrão:
        #   demanda comercial = 48
        #   demanda técnica   = 12
        #   demanda total     = 60
        #   período           = 6 meses
        resultado, indicadores = self._calcular()
        item = resultado.iloc[0]

        # Primeiro comprovamos que a separação das origens da demanda foi
        # preservada. Em seguida comprovamos a soma e a divisão por seis.
        self.assertEqual(item["demanda_comercial"], 48.0)
        self.assertEqual(item["demanda_tecnica"], 12.0)
        self.assertEqual(item["demanda_relevante"], 60.0)
        self.assertEqual(item["media_mensal_saida"], 10.0)
        self.assertEqual(indicadores["meses_demanda"], 6)

    def test_calcula_necessidade_mesmo_com_min_max_zerados(self) -> None:
        """MIN/MAX pendentes não podem esconder a falta projetada na PT02."""

        # A posição padrão possui MIN=0 e MAX=0. Ainda assim, consumo 10 por
        # mês e saldo 4 significam que faltam 6 unidades no picking.
        resultado, _ = self._calcular()
        item = resultado.iloc[0]

        # A necessidade operacional e o diagnóstico de parametrização são
        # informações paralelas: uma não pode esconder a outra.
        self.assertEqual(item["necessidade_ressuprimento"], 6.0)
        self.assertEqual(item["quantidade_sugerida"], 6.0)
        self.assertEqual(item["status_operacional"], "RESSUPRIR")
        self.assertEqual(
            item["status_parametrizacao_pt02"],
            "PARAMETRIZAÇÃO PENDENTE",
        )

    def test_umb_do_mb51_define_unidade_operacional(self) -> None:
        """A unidade da quantidade demandada prevalece sobre a BINMAT."""

        resultado, _ = self._calcular()
        item = resultado.iloc[0]

        # A posição simulada informa PC, enquanto a quantidade histórica do
        # MB51 está em PEÇ. Como a necessidade nasce da quantidade do MB51,
        # sua UMB é a referência operacional correta.
        self.assertEqual(item["unidade_medida"], "PC")
        self.assertEqual(item["unidade_medida_basica"], "PEÇ")
        self.assertEqual(item["unidade_operacional"], "PEÇ")
        self.assertEqual(item["origem_unidade_operacional"], "MB51 - UMB")

    def test_conflito_de_umb_nao_e_ocultado_pela_binmat(self) -> None:
        """Um conflito no MB51 permanece visível, mesmo havendo unidade SAP."""

        demanda = self._criar_demanda(
            umb=None,
            quantidade_umb_distintas=2,
            status_umb="UMB CONFLITANTE",
        )

        resultado, _ = self._calcular(demanda=demanda)
        item = resultado.iloc[0]

        self.assertTrue(pd.isna(item["unidade_operacional"]))
        self.assertEqual(
            item["origem_unidade_operacional"],
            "CONFLITO MB51",
        )

    def test_saldo_igual_a_media_mensal_nao_gera_necessidade(self) -> None:
        """A regra dispara somente quando a PT02 está abaixo da média."""

        # Alteramos somente o saldo PT02 de 4 para 10. Como ele agora é igual
        # à média mensal, a diferença não é positiva.
        resultado, _ = self._calcular(
            saldo_pt02=self._criar_saldo_pt02(
                saldo_f5=10.0,
            )
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_ressuprimento"], 0.0)
        self.assertEqual(item["quantidade_sugerida"], 0.0)
        self.assertEqual(item["status_operacional"], "SEM NECESSIDADE")

    def test_prioriza_maior_demanda_sem_ocultar_picking_zerado(self) -> None:
        """A demanda define a ordem e o saldo zerado permanece visível."""

        # O material 1000001 movimenta muito mais e, por isso, deve aparecer
        # primeiro. O material 1000002 está zerado e continua na fila como
        # alerta, mas esse fato não substitui a demanda como prioridade.
        posicoes = pd.concat(
            [
                self._criar_posicao(
                    material="1000001",
                    posicao="PT02-001-001-001",
                ),
                self._criar_posicao(
                    material="1000002",
                    posicao="PT02-001-003-001",
                ),
            ],
            ignore_index=True,
        )

        saldo_pt02 = pd.concat(
            [
                self._criar_saldo_pt02(
                    material="1000001",
                    posicao="PT02-001-001-001",
                    saldo_f5=900.0,
                ),
                self._criar_saldo_pt02(
                    material="1000002",
                    posicao="PT02-001-003-001",
                    saldo_f5=0.0,
                ),
            ],
            ignore_index=True,
        )

        saldo_t001 = pd.concat(
            [
                self._criar_saldo_t001(
                    material="1000001",
                    saldo_f5=500.0,
                ),
                self._criar_saldo_t001(
                    material="1000002",
                    saldo_f5=500.0,
                ),
            ],
            ignore_index=True,
        )

        demanda = pd.concat(
            [
                self._criar_demanda(
                    material="1000001",
                    comercial=6000.0,
                    tecnica=0.0,
                ),
                self._criar_demanda(
                    material="1000002",
                    comercial=120.0,
                    tecnica=0.0,
                ),
            ],
            ignore_index=True,
        )

        resultado, _ = self._calcular(
            posicoes=posicoes,
            saldo_pt02=saldo_pt02,
            saldo_t001=saldo_t001,
            demanda=demanda,
        )

        self.assertEqual(resultado.iloc[0]["material"], "1000001")
        self.assertEqual(resultado.iloc[0]["media_mensal_saida"], 1000.0)
        self.assertEqual(resultado.iloc[1]["material"], "1000002")
        self.assertEqual(resultado.iloc[1]["saldo_pt02_f5"], 0.0)
        self.assertEqual(resultado.iloc[1]["status_operacional"], "RESSUPRIR")

    def test_limita_sugestao_quando_t001_possui_saldo_parcial(self) -> None:
        """Necessidade 6 com apenas 3 na origem sugere transferência de 3."""

        # A PT02 necessita de 6 unidades, mas a origem possui apenas 3 livres.
        # A ferramenta deve preservar a necessidade e limitar a sugestão.
        resultado, _ = self._calcular(
            saldo_t001=self._criar_saldo_t001(
                saldo_f5=3.0,
            )
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_ressuprimento"], 6.0)
        self.assertEqual(item["quantidade_sugerida"], 3.0)
        self.assertEqual(
            item["status_operacional"],
            "RESSUPRIR PARCIAL",
        )

    def test_arredonda_necessidade_discreta_para_cima(self) -> None:
        """Uma fração de PEÇ exige a próxima unidade física inteira."""

        # Demanda 63 / 6 = média 10,5. Com 4 peças na PT02, a diferença
        # analítica é 6,5, mas a ação necessária para cobrir a média é 7.
        resultado, _ = self._calcular(
            demanda=self._criar_demanda(
                comercial=63.0,
                tecnica=0.0,
                umb="PEÇ",
            ),
            saldo_pt02=self._criar_saldo_pt02(
                saldo_f5=4.0,
            ),
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_ressuprimento"], 6.5)
        self.assertEqual(item["necessidade_operacional"], 7.0)
        self.assertEqual(item["quantidade_sugerida"], 7.0)

    def test_saldo_discreto_insuficiente_gera_parcial(self) -> None:
        """Se faltam 7 PEÇ e a T001 possui 6, a sugestão é parcial."""

        resultado, _ = self._calcular(
            demanda=self._criar_demanda(
                comercial=63.0,
                tecnica=0.0,
                umb="PEÇ",
            ),
            saldo_pt02=self._criar_saldo_pt02(
                saldo_f5=4.0,
            ),
            saldo_t001=self._criar_saldo_t001(
                saldo_f5=6.0,
            ),
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_operacional"], 7.0)
        self.assertEqual(item["quantidade_sugerida"], 6.0)
        self.assertEqual(
            item["status_operacional"],
            "RESSUPRIR PARCIAL",
        )

    def test_unidade_fracionavel_preserva_casas_decimais(self) -> None:
        """Grandezas como grama não devem ser arredondadas para inteiros."""

        resultado, _ = self._calcular(
            demanda=self._criar_demanda(
                comercial=63.0,
                tecnica=0.0,
                umb="G",
            ),
            saldo_pt02=self._criar_saldo_pt02(
                saldo_f5=4.0,
            ),
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_ressuprimento"], 6.5)
        self.assertEqual(item["necessidade_operacional"], 6.5)
        self.assertEqual(item["quantidade_sugerida"], 6.5)

    def test_informa_necessidade_quando_t001_nao_possui_saldo(self) -> None:
        """A ausência na origem não elimina o risco existente no picking."""

        # Saldo PT02 zero gera necessidade integral de 10. Saldo T001 zero
        # impede a execução, mas não elimina nem reduz a necessidade exibida.
        resultado, _ = self._calcular(
            saldo_pt02=self._criar_saldo_pt02(
                saldo_f5=0.0,
            ),
            saldo_t001=self._criar_saldo_t001(
                saldo_f5=0.0,
            ),
        )
        item = resultado.iloc[0]

        self.assertEqual(item["necessidade_ressuprimento"], 10.0)
        self.assertEqual(item["quantidade_sugerida"], 0.0)
        self.assertEqual(item["status_operacional"], "SEM SALDO T001")

    def test_estoque_b5_da_t001_nao_e_usado_para_abastecer(self) -> None:
        """Somente F5 é saldo livre disponível para a transferência."""

        # Existem 100 unidades bloqueadas (B5), porém nenhuma unidade livre
        # (F5). Portanto, a quantidade sugerida para movimentação deve ser 0.
        resultado, _ = self._calcular(
            saldo_t001=self._criar_saldo_t001(
                saldo_f5=0.0,
                saldo_b5=100.0,
            )
        )
        item = resultado.iloc[0]

        self.assertEqual(item["quantidade_sugerida"], 0.0)
        self.assertEqual(item["status_operacional"], "SEM SALDO T001")
        self.assertTrue(item["possui_estoque_bloqueado_t001"])

    def test_posicao_ausente_da_visao_geral_entra_com_f5_zero(
        self,
    ) -> None:
        """Ausência do snapshot gera alerta, sem fingir saldo informado."""

        # O DataFrame vazio representa uma posição existente na BINMAT que
        # não apareceu em nenhuma linha da fotografia VISAO_GERAL.
        saldo_pt02_ausente = pd.DataFrame(
            columns=[
                "material",
                "posicao",
                "tipo_estoque",
                "quantidade_disponivel",
            ]
        )

        resultado, _ = self._calcular(
            saldo_pt02=saldo_pt02_ausente,
        )
        item = resultado.iloc[0]

        # Para fins preventivos, a regra usa zero no cálculo, mas o campo de
        # diagnóstico deixa claro que esse zero foi inferido por ausência.
        self.assertEqual(item["saldo_pt02_f5"], 0.0)
        self.assertTrue(item["saldo_pt02_f5_inferido"])
        self.assertEqual(item["necessidade_ressuprimento"], 10.0)
        self.assertEqual(item["quantidade_sugerida"], 10.0)
        self.assertEqual(item["status_operacional"], "RESSUPRIR")
        self.assertEqual(
            item["status_saldo_pt02"],
            "AUSENTE NA VISAO GERAL - F5 ASSUMIDO ZERO",
        )

    def test_posicao_apenas_com_b5_entra_com_f5_zero(self) -> None:
        """Estoque bloqueado identifica a posição, mas não abastece picking."""

        saldo_apenas_b5 = pd.DataFrame(
            [
                {
                    "material": "1000001",
                    "posicao": "PT02-001-001-001",
                    "tipo_estoque": "B5",
                    "quantidade_disponivel": 5.0,
                }
            ]
        )

        resultado, _ = self._calcular(
            saldo_pt02=saldo_apenas_b5,
        )
        item = resultado.iloc[0]

        self.assertEqual(item["saldo_pt02_f5"], 0.0)
        self.assertEqual(item["saldo_pt02_b5"], 5.0)
        self.assertTrue(item["saldo_pt02_f5_inferido"])
        self.assertEqual(item["necessidade_ressuprimento"], 10.0)
        self.assertEqual(item["status_operacional"], "RESSUPRIR")
        self.assertEqual(
            item["status_saldo_pt02"],
            "SOMENTE B5 - F5 ASSUMIDO ZERO",
        )

    def test_numero_de_meses_informado_altera_a_media(self) -> None:
        """A média usa o parâmetro do cálculo, sem divisor fixo oculto."""

        # Este cenário protege a função contra um divisor 6 escrito de forma
        # fixa. Se o período informado for 3, a regra obrigatoriamente usa 3.
        resultado, _ = self._calcular(
            meses=3,
        )
        item = resultado.iloc[0]

        # A mesma demanda de 60 dividida por 3 meses produz média 20.
        self.assertEqual(item["media_mensal_saida"], 20.0)
        self.assertEqual(item["necessidade_ressuprimento"], 16.0)

    def test_exclui_posicao_de_transicao(self) -> None:
        """Posições logísticas transitórias não entram na operação PT02."""

        # Esta posição possui função logística transitória e foi homologada
        # para permanecer fora do universo operacional de picking definitivo.
        posicoes = self._criar_posicao(
            posicao="PT02-001-002-001",
        )
        saldo_pt02 = self._criar_saldo_pt02(
            posicao="PT02-001-002-001",
        )

        resultado, indicadores = self._calcular(
            posicoes=posicoes,
            saldo_pt02=saldo_pt02,
        )

        # O DataFrame vazio e o indicador zero comprovam tanto a saída quanto
        # a informação de auditoria retornada pela regra.
        self.assertTrue(resultado.empty)
        self.assertEqual(indicadores["pt02_definitivas"], 0)


if __name__ == "__main__":
    unittest.main()
