"""Salute della sessione: quando (e quando NON) chiedere un nuovo OTP all'utente.

Regola H7 del progetto: le decisioni di controllo non si prendono mai su stringhe
umane localizzate. `check()` restituisce un marcatore stabile (`OK`/`EXPIRED`/
`NET_ERROR`) e il coordinator instrada su quello — prima bastava ritoccare (o tradurre)
un messaggio per disattivare in silenzio la riautenticazione.

La distinzione che conta davvero per l'utente: **token morto** (serve un OTP) contro
**blip di rete** (non serve niente, passerà). Confonderli significa far rifare un OTP
inutile a ogni microcaduta della connessione.
"""
from __future__ import annotations

import pytest

import fixtures as FX


def test_sessione_valida(core, cloud, ctx):
    session = core["session"]
    ok, detail, status = session.check(ctx)
    assert ok is True
    assert status == session.STATUS_OK


def test_token_morto_e_expired_non_net_error(core, cloud, ctx):
    """Il BFF risponde ma senza userToken = sessione da riautenticare."""
    session = core["session"]
    cloud.on("/tsp/v1/app/auth/login", {"code": "A00000", "data": {}})
    cloud.on("/auth/oauth2/token", {"code": "A00000"})   # anche il refresh fallisce
    ok, detail, status = session.check(ctx)
    assert ok is False
    assert status == session.STATUS_EXPIRED


def test_errore_di_rete_non_e_una_sessione_scaduta(core, cloud, ctx):
    """Il caso che fa la differenza per l'utente: rete giù ≠ token morto.

    Se questo test si rompe, ogni microcaduta di connessione fa comparire la card
    «Riautentica» e l'utente si ritrova a rifare OTP a vuoto."""
    session = core["session"]
    cloud.on("/tsp/v1/app/auth/login", raises=OSError("connessione rifiutata"))
    ok, detail, status = session.check(ctx)
    assert ok is False
    assert status == session.STATUS_NET_ERROR
    assert status != session.STATUS_EXPIRED


def test_i_marcatori_sono_valori_stabili(core, ctx):
    """I marcatori sono un contratto fra `core/session.py` e il coordinator: se cambiano
    va aggiornato anche `coordinator.SESSION_STATUS_EXPIRED`, altrimenti la reauth non
    scatta più. Il coordinator ha una difesa anti-drift, ma il contratto si fissa qui."""
    session = core["session"]
    assert (session.STATUS_OK, session.STATUS_EXPIRED, session.STATUS_NET_ERROR) == (
        "OK", "EXPIRED", "NET_ERROR")


def test_check_ritorna_sempre_una_tripla(core, cloud, ctx):
    """Il coordinator spacchetta `(ok, detail, status)`: una firma a 2 elementi
    romperebbe l'avvio dell'integrazione."""
    session = core["session"]
    assert len(session.check(ctx)) == 3


def test_refresh_silenzioso_evita_di_disturbare_l_utente(core, cloud, ctx, token_file):
    """P1-3: se l'access_token è scaduto ma il refresh_token è ancora buono, il rinnovo
    deve avvenire in silenzio — senza chiedere un OTP. È il caso NORMALE ogni 12 ore."""
    wake = core["wake"]
    chiamate = {"login": 0}

    def login(path, body):
        chiamate["login"] += 1
        # primo login: token scaduto; dopo il refresh: ok
        if chiamate["login"] == 1:
            return {"code": "A00000", "data": {}}
        return {"data": {"userToken": FX.USER_TOKEN, "tUserId": FX.TUSERID}}

    cloud.on("/tsp/v1/app/auth/login", login)
    cloud.on("/auth/oauth2/token", {"access_token": "at_rinnovato_0123456789"})

    ut, tu = wake._bff_login(ctx)
    assert ut == FX.USER_TOKEN, "il refresh silenzioso non ha recuperato la sessione"
    assert cloud.count("/auth/oauth2/token") == 1


def test_refresh_tentato_anche_con_data_vuoto(core, cloud, ctx, token_file):
    """P1-3 nel dettaglio: il rinnovo si decide sull'ASSENZA di userToken, non sul solo
    `data` non-dict. Un `data` che è un dict ma vuoto saltava il refresh e mandava
    l'utente a rifare un OTP che non serviva."""
    wake = core["wake"]
    cloud.on("/tsp/v1/app/auth/login", {"code": "000000", "data": {}})
    cloud.on("/auth/oauth2/token", {"code": "invalid_grant"})   # refresh non riesce
    wake._bff_login(ctx)
    assert cloud.count("/auth/oauth2/token") == 1, \
        "col `data` vuoto il refresh non è stato nemmeno tentato"


def test_otp_e_email_non_passano_da_argv(core, ctx, monkeypatch):
    """P1-4 (sicurezza): OTP ed email viaggiano nell'ambiente del sottoprocesso, MAI
    nella riga di comando — `/proc/<pid>/cmdline` e `ps aux` sono leggibili da chiunque
    sulla macchina. Si ispeziona la chiamata a subprocess."""
    session = core["session"]
    visto = {}

    class Esito:
        returncode = 0
        stdout = "RESULT: OK"
        stderr = ""

    def finto_run(argv, **kw):
        visto["argv"] = argv
        visto["env"] = kw.get("env") or {}
        return Esito()

    monkeypatch.setattr(session.subprocess, "run", finto_run)
    monkeypatch.setattr(session, "check", lambda _c: (True, "ok", "OK"))
    session.confirm_otp(ctx, "123456")

    riga = " ".join(str(a) for a in visto["argv"])
    assert "123456" not in riga, "OTP esposto in argv (visibile con `ps aux`)"
    assert FX.EMAIL not in riga, "email esposta in argv"
    assert visto["env"].get("OMODA_OTP") == "123456"


def test_codice_otp_vuoto_non_lancia_il_sottoprocesso(core, ctx, monkeypatch):
    session = core["session"]

    def esplodi(*a, **kw):
        raise AssertionError("sottoprocesso lanciato con un codice vuoto")

    monkeypatch.setattr(session.subprocess, "run", esplodi)
    ok, detail = session.confirm_otp(ctx, "   ")
    assert ok is False
