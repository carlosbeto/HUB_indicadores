from datetime import datetime, timedelta, timezone

from hub.lib.session_monitor import registrar_atividade


def test_conta_sessoes_ativas_e_ignora_sessao_expirada(tmp_path):
    banco = tmp_path / "sessoes.sqlite"
    agora = datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc)

    assert registrar_atividade("sessao-a", "home", agora=agora, database_path=banco) == 1
    assert registrar_atividade("sessao-b", "estoques", agora=agora, database_path=banco) == 2

    seis_minutos_depois = agora + timedelta(minutes=6)
    assert (
        registrar_atividade(
            "sessao-b",
            "inventarios",
            agora=seis_minutos_depois,
            database_path=banco,
        )
        == 1
    )


def test_atualizar_mesma_sessao_nao_duplica_contagem(tmp_path):
    banco = tmp_path / "sessoes.sqlite"
    agora = datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc)

    assert registrar_atividade("sessao-a", "home", agora=agora, database_path=banco) == 1
    assert (
        registrar_atividade(
            "sessao-a",
            "estoques",
            agora=agora + timedelta(minutes=1),
            database_path=banco,
        )
        == 1
    )
