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


# ───────────────────── rinnovo del token: perché è fallito ─────────────────────
# Episodio reale del 21/07/2026: il rinnovo silenzioso ha smesso di funzionare e
# l'unica traccia rimasta era un `False` muto. Senza sapere SE il server ha revocato
# il token o SE la rete non ha funzionato, l'unica diagnosi possibile è indovinare.

def test_rinnovo_rifiutato_dal_server_dice_perche(core, cloud, ctx, token_file):
    """Il server risponde `invalid_grant`: revoca esplicita, il motivo va conservato."""
    wake = core["wake"]
    cloud.on("/auth/oauth2/token",
             {"code": 1, "msg": "invalid_grant", "key": "invalid_grant", "ok": False},
             status=401)
    ok, motivo = wake._refresh_token_detail(ctx)
    assert ok is False
    assert motivo == "rifiutato:invalid_grant"


def test_rinnovo_caduto_per_la_rete_non_e_una_revoca(core, cloud, ctx, token_file):
    """La richiesta non parte proprio: è un problema di rete, non del token."""
    wake = core["wake"]
    cloud.on("/auth/oauth2/token", raises=OSError("connessione rifiutata"))
    ok, motivo = wake._refresh_token_detail(ctx)
    assert ok is False
    assert motivo.startswith("rete:")


def test_rete_giu_durante_il_rinnovo_non_fa_chiedere_un_otp(core, cloud, ctx, token_file):
    """Login BFF fallito E rinnovo non partito per la rete = NON è sessione scaduta.

    Se questo test si rompe, ogni microcaduta di connessione fa comparire la card
    «Riautentica» e l'utente brucia un OTP per un problema che passava da solo."""
    session = core["session"]
    cloud.on("/tsp/v1/app/auth/login", {"code": "A00000", "data": {}})
    cloud.on("/auth/oauth2/token", raises=OSError("rete giù"))
    ok, detail, status = session.check(ctx)
    assert ok is False
    assert status == session.STATUS_NET_ERROR


def test_revoca_vera_resta_una_sessione_scaduta(core, cloud, ctx, token_file):
    """Il rovescio del test precedente: se il server REVOCA, l'OTP serve davvero."""
    session = core["session"]
    cloud.on("/tsp/v1/app/auth/login", {"code": "A00000", "data": {}})
    cloud.on("/auth/oauth2/token", {"key": "invalid_grant", "ok": False}, status=401)
    ok, detail, status = session.check(ctx)
    assert ok is False
    assert status == session.STATUS_EXPIRED


def test_motivo_vecchio_non_inganna_il_controllo(core, cloud, ctx, token_file):
    """Un motivo "rete:" stantio non deve mascherare una sessione davvero morta.

    I due eventi appartengono allo stesso giro (frazioni di secondo): fidarsi di un
    marcatore vecchio significherebbe non mostrare mai più la riautenticazione dopo
    un singolo blip di rete."""
    session = core["session"]
    ctx.stato.refresh_motivo = "rete:OSError"
    ctx.stato.refresh_ts = 0.0        # antico
    cloud.on("/tsp/v1/app/auth/login", {"code": "A00000", "data": {}})
    cloud.on("/auth/oauth2/token", {"key": "invalid_grant"}, status=401)
    ok, detail, status = session.check(ctx)
    assert status == session.STATUS_EXPIRED


# ───────────────────── rinnovo proattivo (anticipa la scadenza) ─────────────────────

def test_rinnovo_proattivo_non_tocca_un_token_giovane(core, cloud, ctx, token_file):
    """Nessuna chiamata inutile al cloud finché il token ha vita davanti."""
    session = core["session"]
    assert session.refresh_se_prossimo_a_scadere(ctx) == (False, "non_serve")


def test_rinnovo_proattivo_anticipa_la_scadenza(core, cloud, ctx, token_file):
    """Token a fine vita → si rinnova PRIMA che muoia.

    Il rinnovo reattivo scatta solo dopo la scadenza, cioè fino a un quarto d'ora tardi
    (la cadenza del keep-alive), quando la finestra utile del refresh_token si sta già
    chiudendo. Anticipare è ciò che evita di giocarsi la sessione all'ultimo secondo."""
    import os
    import time as _t

    session = core["session"]
    vecchio = _t.time() - 43200 * 0.95
    os.utime(token_file, (vecchio, vecchio))
    cloud.on("/auth/oauth2/token", data={"access_token": "nuovo_at",
                                         "refresh_token": "nuovo_rt",
                                         "expires_in": 43200})
    rinnovato, motivo = session.refresh_se_prossimo_a_scadere(ctx)
    assert rinnovato is True
    assert motivo == ""


# ───────── freno sui rinnovi già respinti (niente martellamento del gateway) ─────────

def test_un_token_gia_respinto_non_si_ripresenta(core, cloud, ctx, token_file):
    """Il server ha detto `invalid_grant`: ritentare LO STESSO token è solo rumore.

    Senza questo freno ogni chiamata al cloud riprova: misurati 5 tentativi identici in
    6 minuti, e per tutte le ~10 ore di una sessione morta. Presentare a ripetizione una
    credenziale già rifiutata è il comportamento che i gateway sanzionano."""
    wake = core["wake"]
    cloud.on("/auth/oauth2/token", {"key": "invalid_grant"}, status=401)

    ok, motivo = wake._refresh_token_detail(ctx)
    assert (ok, motivo) == (False, "rifiutato:invalid_grant")
    dopo_il_primo = len([c for c in cloud.calls if "oauth2/token" in c["path"]])
    assert dopo_il_primo == 1

    for _ in range(5):
        ok, motivo = wake._refresh_token_detail(ctx)
        assert (ok, motivo) == (False, "rifiutato:gia_respinto")
    chiamate = len([c for c in cloud.calls if "oauth2/token" in c["path"]])
    assert chiamate == 1, f"il freno non ha retto: {chiamate} chiamate invece di 1"


def test_il_freno_si_scioglie_con_un_token_nuovo(core, cloud, ctx, token_file, tmp_path):
    """Dopo un OTP il file contiene un altro refresh_token: si deve poter riprovare.

    È la condizione che rende il freno sicuro: non blocca la ripartenza, blocca solo la
    ripetizione inutile della stessa credenziale."""
    import json as _j

    wake = core["wake"]
    cloud.on("/auth/oauth2/token", {"key": "invalid_grant"}, status=401)
    wake._refresh_token_detail(ctx)
    assert wake._refresh_token_detail(ctx)[1] == "rifiutato:gia_respinto"

    # arriva un token nuovo (come dopo un OTP riuscito)
    token_file.write_text(_j.dumps({"data": {"access_token": "at2",
                                             "refresh_token": "rt_NUOVO_dopo_otp",
                                             "expires_in": 43200}}), encoding="utf-8")
    cloud.on("/auth/oauth2/token", data={"access_token": "at3",
                                         "refresh_token": "rt3", "expires_in": 43200})
    ok, motivo = wake._refresh_token_detail(ctx)
    assert (ok, motivo) == (True, "")


def test_il_freno_non_scatta_sugli_errori_di_rete(core, cloud, ctx, token_file):
    """Un timeout non è un rifiuto: quel token può essere ancora buono, si ritenta."""
    wake = core["wake"]
    cloud.on("/auth/oauth2/token", raises=OSError("timeout"))
    for _ in range(3):
        ok, motivo = wake._refresh_token_detail(ctx)
        assert ok is False and motivo.startswith("rete:")
    chiamate = len([c for c in cloud.calls if "oauth2/token" in c["path"]])
    assert chiamate == 3, "un errore di rete non deve armare il freno"


def test_la_soppressione_non_inquina_il_diagnostico(core, cloud, ctx, token_file):
    """Solo il rifiuto VERO va nel file diagnostico, non le sue ripetizioni soffocate.

    Altrimenti l'unico evento che conta finisce sepolto sotto centinaia di copie."""
    wake = core["wake"]
    registrati = []
    ctx.diag_hook = lambda tipo, **campi: registrati.append((tipo, campi))
    cloud.on("/auth/oauth2/token", {"key": "invalid_grant"}, status=401)
    for _ in range(6):
        wake._refresh_token_detail(ctx)
    refresh = [r for r in registrati if r[0] == "token_refresh"]
    assert len(refresh) == 1, f"attesi 1 evento, trovati {len(refresh)}"
    assert refresh[0][1]["motivo"] == "rifiutato:invalid_grant"


# ───────── il controllo d'avvio dev'essere OSSERVABILE ─────────

async def test_il_monitor_e_armato_prima_del_controllo_sessione(
        hass, config_entry, cloud, monkeypatch):
    """Il controllo sessione d'avvio deve poter finire nel file diagnostico.

    È quel controllo a decidere se aprire la riautenticazione, ed è il primo che si va a
    rileggere quando si indaga su un riavvio. Con il monitor armato DOPO (com'era), quel
    controllo non veniva mai registrato: verificato sul campo su 5 riavvii consecutivi,
    zero controlli d'avvio nel file. Qui si fissa l'ordine, non l'implementazione."""
    from custom_components.omoda9.coordinator import Omoda9Coordinator

    ordine: list[str] = []
    vero_diag = Omoda9Coordinator.async_setup_diag
    vero_check = Omoda9Coordinator.async_check_session

    async def spia_diag(self):
        ordine.append("diag")
        return await vero_diag(self)

    async def spia_check(self):
        ordine.append("sessione")
        return await vero_check(self)

    monkeypatch.setattr(Omoda9Coordinator, "async_setup_diag", spia_diag)
    monkeypatch.setattr(Omoda9Coordinator, "async_check_session", spia_check)
    # stesse neutralizzazioni della fixture `integrazione_avviata`: qui non si possono
    # riusare perché le spie vanno installate PRIMA del setup, che la fixture fa da sé.
    monkeypatch.setattr(Omoda9Coordinator, "_provision_certs",
                        lambda self: (True, "cert finti (test)"))
    monkeypatch.setattr(Omoda9Coordinator, "_connect_car", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_keepalive", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_telemetry_poll", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_drive_watch", lambda self: None)

    async def _niente_backfill(self):
        return None

    monkeypatch.setattr(Omoda9Coordinator, "async_ensure_vehicle_identity", _niente_backfill)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    try:
        assert "diag" in ordine and "sessione" in ordine
        assert ordine.index("diag") < ordine.index("sessione"), \
            f"monitor armato troppo tardi: {ordine}"
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


async def test_armare_il_monitor_due_volte_e_innocuo(hass, config_entry, cloud, monkeypatch):
    """`async_setup_entry` lo arma presto e `async_start` lo richiama: la seconda
    chiamata non deve creare un secondo scrittore sullo stesso file."""
    from custom_components.omoda9.coordinator import Omoda9Coordinator

    monkeypatch.setattr(Omoda9Coordinator, "_provision_certs",
                        lambda self: (True, "cert finti (test)"))
    monkeypatch.setattr(Omoda9Coordinator, "_connect_car", lambda self: None)
    coord = Omoda9Coordinator(hass, config_entry)
    finto = object()
    coord._diag = finto
    await coord.async_setup_diag()
    assert coord._diag is finto, "il monitor già armato è stato sostituito"
