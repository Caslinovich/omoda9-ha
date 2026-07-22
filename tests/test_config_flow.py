"""Config flow, riautenticazione e Repair del PIN — i tre punti in cui l'utente
non tecnico interagisce con l'integrazione quando qualcosa non va.

Sono anche i percorsi in cui un errore si paga caro: il codice OTP è **usa e getta**
(un flow che lo spende e poi fallisce costringe a ricominciare da capo) e il PIN
sbagliato, ripetuto, blocca l'account Chery.
"""
from __future__ import annotations

import pytest
from homeassistant import config_entries, data_entry_flow

import fixtures as FX
from custom_components.omoda9.const import CONF_EMAIL, CONF_PIN, CONF_VIN, DOMAIN


@pytest.fixture
def flusso_ok(monkeypatch):
    """Backend che coopera: OTP inviato, token coniato, un veicolo trovato."""
    from custom_components.omoda9 import config_flow as cf

    monkeypatch.setattr(cf, "_send_otp", lambda hass, data: (True, "codice inviato"))
    monkeypatch.setattr(cf, "_mint_token", lambda hass, data, code: (True, "token ok"))
    monkeypatch.setattr(cf, "_discover",
                        lambda hass, data: (True, FX.TUSERID, [FX.VIN], "ok"))
    monkeypatch.setattr(cf, "_finalize_token", lambda hass, vin: True)
    monkeypatch.setattr(cf, "_cleanup_pending", lambda hass: None)
    return cf


DATI_UTENTE = {CONF_EMAIL: FX.EMAIL, CONF_PIN: FX.PIN}


def _forza_blocco(coordinator) -> None:
    """Porta l'anti-lockout del veicolo allo stato "bloccato", come dopo N PIN errati.

    Si passa dall'API pubblica (`attempt()`) invece di scrivere nei contatori: così il
    test resta valido anche se la rappresentazione interna cambia — ed è la stessa
    ragione per cui lo stato è stato incapsulato in P2-3.

    P2-6: il blocco è del VEICOLO, quindi si agisce sul contesto di quel coordinator."""
    lockout = coordinator.ctx.lockout
    for _ in range(lockout.max_fail):
        with lockout.attempt() as tentativo:
            tentativo.fallito()
    assert lockout.is_locked(), "prerequisito: l'anti-lockout doveva essere scattato"


async def test_configurazione_completa(hass, flusso_ok):
    """Il percorso normale: email + PIN → OTP → entry creato col VIN scoperto."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], DATI_UTENTE)
    assert result["step_id"] == "otp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"})
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VIN] == FX.VIN
    assert result["data"][CONF_EMAIL] == FX.EMAIL


async def test_invio_otp_fallito_resta_nel_primo_passo(hass, monkeypatch):
    """Se l'OTP non parte non si prosegue: chiedere un codice mai inviato manderebbe
    l'utente a cercare un'email che non arriverà."""
    from custom_components.omoda9 import config_flow as cf

    monkeypatch.setattr(cf, "_send_otp", lambda hass, data: (False, "email.not.exists"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], DATI_UTENTE)

    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "otp_send_failed"


async def test_otp_errato_ripulisce_il_token_a_meta(hass, monkeypatch):
    """Un OTP rifiutato deve lasciare il disco pulito: un `pending_token` orfano
    verrebbe scambiato per una sessione valida al tentativo successivo."""
    from custom_components.omoda9 import config_flow as cf

    pulizie = {"n": 0}
    monkeypatch.setattr(cf, "_send_otp", lambda hass, data: (True, ""))
    monkeypatch.setattr(cf, "_mint_token",
                        lambda hass, data, code: (False, "codice scaduto"))
    monkeypatch.setattr(cf, "_cleanup_pending",
                        lambda hass: pulizie.__setitem__("n", pulizie["n"] + 1))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATI_UTENTE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "000000"})

    assert result["errors"]["base"] == "otp_invalid"
    assert pulizie["n"] == 1


async def test_piu_veicoli_chiede_quale(hass, flusso_ok, monkeypatch):
    """Account con più auto: si deve poter scegliere, non prendere la prima."""
    altro = "LZZBBBBBB9Z8Y7X6W"     # VIN_PLACEHOLDER: sintetico
    monkeypatch.setattr(flusso_ok, "_discover",
                        lambda hass, data: (True, FX.TUSERID, [FX.VIN, altro], "ok"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATI_UTENTE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"})
    assert result["step_id"] == "select_vehicle"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VIN: altro})
    assert result["data"][CONF_VIN] == altro


async def test_stesso_veicolo_non_si_configura_due_volte(hass, flusso_ok, config_entry):
    """Il VIN è l'identità univoca: un secondo entry darebbe due set di entità in
    conflitto sulla stessa auto."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATI_UTENTE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"})

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_token_non_spostabile_fa_fallire_il_flow(hass, flusso_ok, monkeypatch):
    """Senza token in posizione il coordinator non potrebbe autenticarsi: meglio un
    abort esplicito che un'integrazione creata e subito rotta."""
    monkeypatch.setattr(flusso_ok, "_finalize_token", lambda hass, vin: False)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATI_UTENTE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"})

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "token_move_failed"


# ───────────────────────── riconfigurazione PIN ─────────────────────────
async def test_riconfigura_pin_azzera_sempre_il_lockout(hass, integrazione_avviata):
    """P0-2: il reset dell'anti-lockout deve avvenire ANCHE reinserendo lo STESSO PIN.

    È il caso reale segnalato: l'utente riconferma il PIN (che era giusto), sembra
    risolto, ma i comandi restano bloccati in silenzio fino allo scadere della finestra."""
    coord = hass.data[DOMAIN][integrazione_avviata.entry_id]
    _forza_blocco(coord)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE,
                 "entry_id": integrazione_avviata.entry_id})
    assert result["step_id"] == "reconfigure"

    # STESSO PIN di prima: è proprio il caso che prima non sbloccava
    await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PIN: FX.PIN})
    await hass.async_block_till_done()

    assert coord.ctx.lockout.tentativi_falliti == 0, \
        "lockout ancora attivo dopo la riconfigurazione"


async def test_form_pin_non_mostra_il_pin_attuale(hass, integrazione_avviata):
    """P1-5 (sicurezza): il PIN è una credenziale. Non deve comparire pre-riempito nel
    form — finirebbe negli screenshot che l'utente allega alle richieste di supporto."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE,
                 "entry_id": integrazione_avviata.entry_id})

    schema = result["data_schema"].schema
    campo = next(k for k in schema if str(k) == CONF_PIN)
    assert getattr(campo, "default", None) in (None, vol_undefined()), \
        "il form ripropone il PIN attuale come default"
    # ed è un campo password, non testo in chiaro
    selettore = schema[campo]
    assert "password" in str(selettore.config).lower()


def vol_undefined():
    import voluptuous as vol
    return vol.UNDEFINED


async def test_pin_vuoto_rifiutato(hass, integrazione_avviata):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE,
                 "entry_id": integrazione_avviata.entry_id})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIN: "   "})
    assert result["errors"]["base"] == "pin_required"


# ───────────────────────── Repair «PIN comandi errato» ─────────────────────────
async def test_repair_pin_sblocca_e_applica(hass, integrazione_avviata):
    """Il Repair è il rimedio che l'utente non tecnico incontra davvero: deve
    scrivere il nuovo PIN E azzerare il blocco, altrimenti "si aggiusta" solo in apparenza."""
    from custom_components.omoda9 import repairs

    coord = hass.data[DOMAIN][integrazione_avviata.entry_id]
    _forza_blocco(coord)

    flow = await repairs.async_create_fix_flow(
        hass, f"pin_wrong_{integrazione_avviata.entry_id}",
        {"entry_id": integrazione_avviata.entry_id})
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["step_id"] == "pin"

    result = await flow.async_step_pin({CONF_PIN: "1234"})
    await hass.async_block_till_done()

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert integrazione_avviata.data[CONF_PIN] == "1234"
    coord_dopo = hass.data[DOMAIN][integrazione_avviata.entry_id]
    assert coord_dopo.ctx.lockout.tentativi_falliti == 0


async def test_repair_senza_entry_si_interrompe(hass):
    """Entry già rimosso mentre l'avviso era aperto: si abortisce senza esplodere."""
    from custom_components.omoda9 import repairs

    flow = await repairs.async_create_fix_flow(hass, "pin_wrong_x",
                                               {"entry_id": "non_esiste"})
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


# ───────────────────── riautenticazione: nessun OTP non richiesto ─────────────────────
# Episodio reale del 21/07/2026: la sessione è morta alle 22:21 e all'utente sono
# arrivate TRE mail con codice OTP che non aveva chiesto. Una per la scadenza, due
# per altrettanti riavvii di Home Assistant — perché il flow di reauth si ricrea a
# ogni avvio finché la sessione è morta, e all'epoca spediva un codice appena aperto.
# In più il reinvio era nascosto dietro «lascia il campo vuoto e conferma», che il
# frontend rifiuta perché il campo è obbligatorio: l'utente restava con in mano solo
# un codice ormai scaduto e nessun modo di chiederne un altro.


@pytest.fixture
def spia_otp(hass, integrazione_avviata, monkeypatch):
    """Conta gli invii di OTP e permette di pilotare l'esito di invio/conferma."""
    coord = hass.data[DOMAIN][integrazione_avviata.entry_id]
    stato = {"inviati": 0, "invio_ok": True, "codice_giusto": "123456"}

    def _request_otp():
        stato["inviati"] += 1
        return stato["invio_ok"], ("codice inviato" if stato["invio_ok"]
                                   else "invio non riuscito")

    def _confirm_otp(code):
        giusto = code == stato["codice_giusto"]
        return giusto, ("token coniato" if giusto else "codice errato")

    monkeypatch.setattr(coord, "_request_otp", _request_otp)
    monkeypatch.setattr(coord, "_confirm_otp", _confirm_otp)
    return stato


async def _apri_reauth(hass, entry):
    """Apre la riautenticazione come fa Home Assistant quando la sessione muore."""
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )


async def test_aprire_la_riautenticazione_non_manda_nessun_otp(
        hass, integrazione_avviata, spia_otp):
    """LA regressione da bloccare: aprire la pagina non deve spedire niente."""
    result = await _apri_reauth(hass, integrazione_avviata)
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    assert spia_otp["inviati"] == 0, "aprire la reauth ha spedito un OTP non richiesto"


async def test_riavvii_ripetuti_non_generano_mail(hass, integrazione_avviata, spia_otp):
    """Tre aperture del flow (= tre riavvii di HA a sessione morta) = zero mail."""
    for _ in range(3):
        result = await _apri_reauth(hass, integrazione_avviata)
        hass.config_entries.flow.async_abort(result["flow_id"])
    assert spia_otp["inviati"] == 0


async def test_il_codice_parte_solo_su_richiesta_esplicita(
        hass, integrazione_avviata, spia_otp):
    """L'unico modo di far partire un OTP è chiederlo dal menu."""
    result = await _apri_reauth(hass, integrazione_avviata)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "send_code"})
    assert spia_otp["inviati"] == 1
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "enter_code"


async def test_codice_sbagliato_non_lascia_in_trappola(
        hass, integrazione_avviata, spia_otp):
    """Dopo un codice rifiutato si torna al menu, da cui se ne può chiedere uno nuovo.

    È il vicolo cieco in cui l'utente è finito davvero: codice scaduto in mano e
    nessun pulsante per farsene mandare un altro."""
    result = await _apri_reauth(hass, integrazione_avviata)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "send_code"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "000000"})
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    assert spia_otp["inviati"] == 1, "un codice errato non deve reinviare da solo"

    # ...e da qui il codice nuovo si può chiedere, con un tap
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "send_code"})
    assert spia_otp["inviati"] == 2
    assert result["step_id"] == "enter_code"


async def test_invio_fallito_torna_al_menu_col_motivo(
        hass, integrazione_avviata, spia_otp):
    """Se la mail non parte l'utente deve saperlo, non restare ad aspettarla."""
    spia_otp["invio_ok"] = False
    result = await _apri_reauth(hass, integrazione_avviata)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "send_code"})
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    assert "invio non riuscito" in result["description_placeholders"]["reason"]


async def test_riautenticazione_riuscita(hass, integrazione_avviata, spia_otp):
    """Il percorso felice: codice giusto → entry ricaricato."""
    result = await _apri_reauth(hass, integrazione_avviata)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "send_code"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"})
    await hass.async_block_till_done()
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_si_puo_inserire_un_codice_gia_in_mano(
        hass, integrazione_avviata, spia_otp):
    """Chi ha già un codice valido non deve essere costretto a farsene mandare un altro."""
    result = await _apri_reauth(hass, integrazione_avviata)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "enter_code"})
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "enter_code"
    assert spia_otp["inviati"] == 0
