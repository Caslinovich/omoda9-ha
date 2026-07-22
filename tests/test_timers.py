"""Ciclo di vita dei timer: i poll che continuavano a contattare il cloud per ore.

Contesto (audit P0-4/P0-5): il follow-up HV/ricarica si auto-rischedula. Bastava che una
lettura fosse già "in volo" quando l'integrazione veniva scaricata, o che l'utente
spegnesse l'aggiornamento automatico durante una carica, perché il timer si ri-armasse e
il ciclo proseguisse — invisibile, ma con conseguenze reali: consumo della batteria 12V
e contesa con l'app ufficiale (il cloud Chery ammette UNA sessione per account).

Questi test descrivono l'invariante in modo indipendente dall'implementazione — «dopo
lo stop nessun timer resta armato» — così P2-4 può riscrivere completamente il
meccanismo (registro unico degli unsub) e restare verificabile.
"""
from __future__ import annotations

import pytest

from custom_components.omoda9.timers import DRIVE_WATCH, HV_POLL, POLL


def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


def _timer_armati(coord) -> set[str]:
    """I timer attualmente armati, per nome (P2-4: registro unico)."""
    return coord._timers.armed()


@pytest.fixture
def coord(hass, integrazione_avviata, monkeypatch):
    """Coordinator con la sonda neutralizzata: `async_probe` uscirebbe in rete."""
    c = _coordinator(hass, integrazione_avviata)

    async def finta_probe(force: bool = False):
        return None

    monkeypatch.setattr(c, "async_probe", finta_probe)
    return c


async def test_stop_non_lascia_timer_armati(hass, coord, monkeypatch):
    """Dopo `async_stop` nessun timer deve restare in piedi — è l'invariante di base."""
    # il follow-up si arma solo se c'è qualcosa da seguire (spina o alta tensione)
    monkeypatch.setattr(coord, "_is_plugged", lambda: True)
    coord.poll_enabled = True
    coord._arm_hv_followup()
    assert coord._timers.is_armed(HV_POLL), "prerequisito: il follow-up era armato"

    coord.async_stop()
    assert _timer_armati(coord) == set(), _timer_armati(coord)


async def test_dopo_lo_stop_i_timer_non_si_riarmano(hass, coord, monkeypatch):
    """P0-4, il caso reale: una lettura già in volo torna DOPO lo stop e prova a
    ri-armare il follow-up. Il ciclo deve restare chiuso."""
    monkeypatch.setattr(coord, "_is_plugged", lambda: True)   # ci sarebbe da seguire
    coord.poll_enabled = True
    coord.async_stop()

    coord._arm_hv_followup()          # è ciò che faceva la probe al ritorno
    assert not coord._timers.is_armed(HV_POLL), "timer ri-armato dopo lo stop (poll orfano)"

    await coord.async_probe(force=True)
    assert not coord._timers.is_armed(HV_POLL)


async def test_spegnere_aggiornamento_automatico_ferma_anche_la_ricarica(hass, coord, monkeypatch):
    """P0-5: con l'auto in carica il follow-up gira ogni 2 minuti. Spegnendo
    l'interruttore «Aggiornamento automatico» deve fermarsi TUTTO — prima restava
    attivo proprio il ciclo più frequente, quello della ricarica."""
    monkeypatch.setattr(coord, "_is_plugged", lambda: True)
    coord.poll_enabled = True
    coord._arm_hv_followup()
    assert coord._timers.is_armed(HV_POLL)

    coord.set_poll_enabled(False)
    assert not coord._timers.is_armed(HV_POLL), "il follow-up ricarica è sopravvissuto allo switch OFF"
    assert not coord._timers.is_armed(POLL)
    assert not coord._timers.is_armed(DRIVE_WATCH)
    assert coord._hv_poll_count == 0


async def test_a_poll_spento_un_push_non_riaccende_il_ciclo(hass, coord, monkeypatch):
    """L'altra via d'ingresso: un messaggio dell'auto (spina collegata) non deve
    riaccendere il follow-up quando l'utente ha spento l'aggiornamento automatico."""
    monkeypatch.setattr(coord, "_is_plugged", lambda: True)
    coord.poll_enabled = False

    coord._arm_hv_followup()
    assert not coord._timers.is_armed(HV_POLL)


async def test_il_follow_up_si_ferma_da_solo_quando_l_auto_si_spegne(hass, coord, monkeypatch):
    """Senza spina né alta tensione il ciclo deve chiudersi da sé: è ciò che impedisce
    al poll di girare all'infinito su un'auto ferma."""
    monkeypatch.setattr(coord, "_is_plugged", lambda: False)
    monkeypatch.setattr(coord, "_is_hv_on", lambda: False)
    coord.poll_enabled = True

    coord._arm_hv_followup()
    assert not coord._timers.is_armed(HV_POLL)
    assert coord._hv_poll_count == 0


async def test_cap_di_sicurezza_sul_numero_di_letture(hass, coord, monkeypatch):
    """Anche restando la spina collegata il loop ha un tetto: una carica che non
    finisce mai non deve tradursi in letture cloud infinite."""
    from custom_components.omoda9.const import CHARGING_POLL_MAX

    monkeypatch.setattr(coord, "_is_plugged", lambda: True)
    coord.poll_enabled = True
    coord._hv_poll_count = CHARGING_POLL_MAX

    coord._arm_hv_followup()
    assert not coord._timers.is_armed(HV_POLL), "cap superato ma il loop continua"
    assert coord._hv_poll_count == 0


async def test_unload_smonta_tutto(hass, integrazione_avviata):
    """Scaricando l'integrazione non devono restare né timer né il coordinator in
    `hass.data`: è la condizione perché un reload riparta pulito."""
    from custom_components.omoda9.const import DOMAIN

    coord = _coordinator(hass, integrazione_avviata)
    await hass.config_entries.async_unload(integrazione_avviata.entry_id)
    await hass.async_block_till_done()

    assert integrazione_avviata.entry_id not in hass.data.get(DOMAIN, {})
    assert _timer_armati(coord) == set(), _timer_armati(coord)
    assert coord._timers.closing is True


# NB: la verifica «PIN ed email non finiscono nell'ambiente del processo» si è spostata
# in `test_context.py`, dove ha una forma più forte: dopo P2-6 non ci finiscono MAI, quindi
# non c'è nulla da ripulire all'unload — una garanzia che non dipende dall'unload.


# ─────────────────── reload dell'entry: solo per le opzioni ───────────────────
# `add_update_listener` scatta a OGNI async_update_entry, anche quando cambia solo
# `entry.data`. Prima l'entry veniva ricaricata anche dal backfill dell'identità
# veicolo (task in background del setup) e dai percorsi PIN, che però si ricaricano
# già da soli: reload doppi, e uno di essi restava appeso allo spegnimento di HA.

def _spia_reload(hass, monkeypatch) -> list[str]:
    """Registra OGNI reload dell'entry, con qualunque API sia richiesto.

    Spiare solo `async_schedule_reload` renderebbe il test inutile: il codice
    difettoso usava `async_reload`, quindi la spia non vedeva nulla e l'asserzione
    "nessun reload" passava per caso anche col bug presente.
    """
    chiamate: list[str] = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload",
                        lambda entry_id: chiamate.append(entry_id))

    async def _reload(entry_id: str) -> bool:
        chiamate.append(entry_id)
        return True

    monkeypatch.setattr(hass.config_entries, "async_reload", _reload)
    return chiamate


async def test_un_aggiornamento_dei_soli_dati_non_ricarica_l_entry(
        hass, integrazione_avviata, monkeypatch):
    """Scrivere in `entry.data` (es. backfill nome veicolo) NON deve ricaricare."""
    chiamate = _spia_reload(hass, monkeypatch)

    hass.config_entries.async_update_entry(
        integrazione_avviata,
        data={**integrazione_avviata.data, "vehicle_name": "Auto di prova"})
    await hass.async_block_till_done()

    assert chiamate == [], "un aggiornamento dei soli dati ha ricaricato l'entry"


async def test_un_cambio_di_opzioni_ricarica_l_entry(
        hass, integrazione_avviata, monkeypatch):
    """Le opzioni (intervalli di poll) si applicano al setup → il reload serve davvero."""
    chiamate = _spia_reload(hass, monkeypatch)

    hass.config_entries.async_update_entry(
        integrazione_avviata,
        options={**dict(integrazione_avviata.options or {}), "poll_normal_min": 45})
    await hass.async_block_till_done()

    assert chiamate == [integrazione_avviata.entry_id], \
        "un cambio di opzioni non ha ricaricato l'entry"


# ───────── lo stato «auto sveglia» deve SCADERE ─────────
# Trovato in campo il 2026-07-22: il flag veniva acceso a ogni messaggio dell'auto e non si
# spegneva mai — `on` da quasi 4 ore su un'auto ferma, con la finestra prevista di 5 minuti.
# Il danno vero non è il sensore: `do_wake` chiede a questo stato se l'auto è già sveglia,
# quindi il pulsante «Sveglia auto» rispondeva «già sveglia» senza mandare nulla.

async def test_auto_sveglia_scade_dopo_la_finestra(hass, coord, monkeypatch):
    """Passata la finestra senza messaggi, l'auto NON è più considerata sveglia."""
    import time as _t

    coord.awake_window = 300
    coord._last_msg_ts = _t.time()
    assert coord._auto_e_sveglia() is True

    coord._last_msg_ts = _t.time() - 301        # ultimo messaggio oltre la finestra
    assert coord._auto_e_sveglia() is False, \
        "lo stato «sveglia» non scade: il pulsante Sveglia auto resta inutilizzabile"


async def test_senza_nessun_messaggio_non_e_sveglia(hass, coord):
    """Prima di qualsiasi messaggio l'auto non è sveglia (nessun falso positivo)."""
    coord._last_msg_ts = 0.0
    assert coord._auto_e_sveglia() is False


async def test_la_sveglia_interroga_lo_stato_reale(hass, coord, monkeypatch):
    """`do_wake` deve ricevere lo stato calcolato, non il flag memorizzato.

    È il punto in cui il difetto faceva danno: con un flag acceso per sempre l'SMS di
    sveglia non partiva più e nemmeno il ripiego su «Localizza»."""
    import time as _t

    visto = {}

    def finto_do_wake(ctx, publish, is_awake=None, send_sms=True):
        visto["awake"] = is_awake() if is_awake else None
        return {"ok": True, "online": True}

    from custom_components.omoda9.core import wake as WAKE

    monkeypatch.setattr(WAKE, "do_wake", finto_do_wake)
    coord.awake_window = 300
    coord._last_msg_ts = _t.time() - 301        # auto ferma da oltre la finestra
    coord.data["awake"] = True                  # ...ma il vecchio flag è rimasto acceso
    await hass.async_add_executor_job(coord._wake)
    assert visto["awake"] is False, \
        "la sveglia ha creduto al flag memorizzato invece che allo stato reale"
