"""Login via SMS: la forma esatta delle richieste, e il numero che non deve trapelare.

Perché questi test esistono. La forma del login mobile non è documentata da nessuna parte:
è stata ricavata decompilando l'app (`UserService::phoneVerifyLogin`) e confermata una volta
sola contro il server vero. Sono quattro dettagli che sembrano arbitrari e che, se qualcuno
li «riordina» in buona fede, fanno fallire il login con un messaggio che accusa il codice OTP:

  * l'identità NON è il numero, è la stringa composita `APP-LOGIN@<numero>_<prefisso>`;
  * `grant_type=mobile` (non `email`, non `sms`);
  * i parametri viaggiano nel **BODY**, mentre il ramo e-mail li manda in **QUERY**;
  * il codice è cifrato SM4 come nel ramo e-mail, non in chiaro.

Senza questi test la suite resta verde mentre il login è rotto, perché tutto il resto della
catena è finto. Qui non si verifica che il server accetti — quello si può solo provare dal
vivo — ma che il client continui a produrre ciò che una volta ha funzionato.

La seconda metà del file guarda il numero di telefono come DATO PERSONALE: negli account SMS
è l'identità di login e, a differenza di un OTP, non scade mai.
"""
from __future__ import annotations

import json

import fixtures as FX


# ───────────────────────── forma delle richieste ─────────────────────────

def test_identita_mobile_e_composita(core):
    """`APP-LOGIN@<numero>_<prefisso>`: il numero nudo NON funziona (verificato dal vivo)."""
    pt = core["prova_token"]
    p = pt.build_params_mobile(FX.PHONE, FX.AREA_CODE, "123456")

    assert p["mobile"] == f"APP-LOGIN@{FX.PHONE}_{FX.AREA_CODE}"
    assert p["grant_type"] == "mobile"
    assert p["loginType"] == "mobile"
    assert p["code"] != "123456", "il codice deve essere cifrato SM4, non in chiaro"


def test_il_numero_viene_ripulito_prima_di_comporre_l_identita(core):
    """Difesa in profondità: la normalizzazione vera sta nel config flow, ma se un numero
    sporco arrivasse fin qui l'identità non deve contenere spazi o `+`."""
    pt = core["prova_token"]
    p = pt.build_params_mobile(f"+{FX.AREA_CODE} {FX.PHONE}", FX.AREA_CODE, "123456")
    assert " " not in p["mobile"] and "+" not in p["mobile"]


def test_mobile_va_nel_body_ed_email_in_query(core, monkeypatch):
    """Il dettaglio che fa la differenza fra un token coniato e «codice non valido».

    Verificato dal vivo il 2026-08-02: la stessa identità mandata in query viene rifiutata."""
    pt = core["prova_token"]
    visti: list[dict] = []

    class _Risposta:
        status_code = 200
        text = "{}"
        def json(self):
            return {"access_token": FX.ACCESS_TOKEN}

    def _post(url, **kw):
        visti.append(kw)
        return _Risposta()

    monkeypatch.setattr(pt.requests, "post", _post)

    pt.call("", "123456", phone=FX.PHONE, area=FX.AREA_CODE, verbose=False)
    assert "data" in visti[-1] and "params" not in visti[-1], "il login mobile deve usare il BODY"

    pt.call(FX.EMAIL, "123456", verbose=False)
    assert "params" in visti[-1] and "data" not in visti[-1], "il login email deve usare la QUERY"


def test_request_otp_usa_il_ramo_sms_e_non_mette_il_numero_in_argv(core, ctx, monkeypatch):
    """Due cose in un colpo: il comando giusto, e l'invariante P1-4.

    Il numero è un dato personale e la riga di comando è leggibile da qualsiasi utente della
    macchina (`ps`, `/proc/<pid>/cmdline`): deve viaggiare nell'ambiente, mai in argv."""
    session = core["session"]
    ctx.phone, ctx.area_code = FX.PHONE, FX.AREA_CODE
    visto: dict = {}

    class _Esito:
        returncode = 0
        stdout = "sendSmsCode -> HTTP 200\nRESULT: OK\n"
        stderr = ""

    def _run(argv, **kw):
        visto["argv"], visto["env"] = argv, kw.get("env", {})
        return _Esito()

    monkeypatch.setattr(session.subprocess, "run", _run)
    assert session.request_otp(ctx) is True

    assert "invia-sms" in visto["argv"], "account col telefono: deve partire il ramo SMS"
    assert FX.PHONE not in " ".join(visto["argv"]), "numero in argv: visibile in `ps`"
    assert visto["env"]["OMODA_PHONE"] == FX.PHONE
    assert visto["env"]["OMODA_AREA"] == FX.AREA_CODE


def test_senza_telefono_resta_il_ramo_email(core, ctx, monkeypatch):
    """La regressione che conta di più: il ramo e-mail funzionava già e deve continuare.
    Vale anche per gli entry creati PRIMA di questa versione, che non hanno la chiave."""
    session = core["session"]
    visto: dict = {}

    class _Esito:
        returncode = 0
        stdout = "RESULT: OK\n"
        stderr = ""

    monkeypatch.setattr(session.subprocess, "run",
                        lambda argv, **kw: (visto.update(argv=argv) or _Esito()))
    assert session.request_otp(ctx) is True
    assert "invia" in visto["argv"] and "invia-sms" not in visto["argv"]


# ───────────────────────── il motivo mostrato all'utente ─────────────────────────

def test_il_motivo_non_e_la_sentinella(core):
    """`RESULT: FAIL` è il protocollo fra processi, non una spiegazione.

    Prendendo l'ultima riga si otteneva sempre quella, e la diagnostica vera (blocco WAF,
    captcha, client TLS mancante, chiave d'errore del server) restava invisibile all'utente."""
    session = core["session"]
    out = ("[SMS] invio codice al numero +39 ***4747\n"
           "sendSmsCode -> HTTP 200 key=user.not.exists msg=numero non registrato\n"
           "RESULT: FAIL\n")
    riga = session._riga_utile(out, 1)
    assert "RESULT:" not in riga
    assert "user.not.exists" in riga


def test_il_motivo_ripiega_sul_returncode_se_non_c_e_altro(core):
    session = core["session"]
    assert session._riga_utile("RESULT: FAIL\n", 2) == "rc=2"
    assert session._riga_utile("", 3) == "rc=3"


# ───────────────────────── il numero come dato personale ─────────────────────────

def test_il_numero_non_finisce_nel_messaggio_di_esito(core, ctx, monkeypatch):
    """Quella frase non resta nel config flow: diventa lo stato di
    `sensor.omoda9_stato_sessione` (→ recorder, backup) ed è esportata verbatim nella
    diagnostica, fuori da ogni deny-list. Va mascherata alla sorgente."""
    session = core["session"]
    ctx.phone, ctx.area_code = FX.PHONE, FX.AREA_CODE
    messaggi: list[str] = []

    class _Esito:
        returncode = 0
        stdout = "RESULT: OK\n"
        stderr = ""

    monkeypatch.setattr(session.subprocess, "run", lambda argv, **kw: _Esito())
    session.request_otp(ctx, emit=messaggi.append)

    tutto = " ".join(messaggi)
    assert FX.PHONE not in tutto, "numero in chiaro nel messaggio che finisce nel sensore"
    assert FX.PHONE[-4:] in tutto, "le ultime cifre servono a riconoscere «è il mio numero»"


def test_i_log_del_conio_non_contengono_il_codice_ne_il_numero(core, monkeypatch, capsys):
    """Lo stdout di `prova_token` viene loggato da Home Assistant, e i log finiscono nelle
    issue pubbliche: può uscire la FORMA del tentativo, non le credenziali."""
    pt = core["prova_token"]

    class _Risposta:
        status_code = 200
        text = "{}"
        def json(self):
            return {"access_token": FX.ACCESS_TOKEN}

    monkeypatch.setattr(pt.requests, "post", lambda url, **kw: _Risposta())
    pt.call("", "481923", phone=FX.PHONE, area=FX.AREA_CODE, verbose=True)

    stampato = capsys.readouterr().out
    assert "481923" not in stampato, "codice OTP in chiaro nell'output loggato da HA"
    assert FX.PHONE not in stampato, "numero in chiaro nell'output loggato da HA"
    assert FX.ACCESS_TOKEN not in stampato, "token in chiaro"
    assert "grant" in stampato or "mobile" in stampato, "la forma del tentativo si è persa"


async def test_la_diagnostica_non_espone_il_telefono(hass, integrazione_avviata):
    """Due vie diverse, entrambe reali: la chiave in `entry.data` e il numero scritto dentro
    una frase discorsiva. Chiudere solo la prima lascia aperta la seconda."""
    from custom_components.omoda9.const import DOMAIN
    from custom_components.omoda9.diagnostics import async_get_config_entry_diagnostics

    coord = hass.data[DOMAIN][integrazione_avviata.entry_id]
    coord.phone, coord.area_code = FX.PHONE, FX.AREA_CODE
    coord.data = {**coord.data,
                  "session_detail": f"Codice inviato al numero +{FX.AREA_CODE} {FX.PHONE}"}
    hass.config_entries.async_update_entry(
        integrazione_avviata,
        data={**integrazione_avviata.data, "phone": FX.PHONE, "area_code": FX.AREA_CODE})

    blob = json.dumps(await async_get_config_entry_diagnostics(hass, integrazione_avviata))
    assert FX.PHONE not in blob, "numero di telefono in chiaro nella diagnostica scaricabile"
