"""Mappatura della telemetria: dagli envelope MQTT dell'auto allo stato in HA.

Qui non ci sono bug noti da bloccare — il parsing è la parte che ha sempre funzionato.
Il valore è un altro: fissare il contratto con il backend. Se un giorno Chery cambia la
forma dei messaggi, questi test lo dicono subito, con un envelope sotto gli occhi,
invece di lasciare i sensori fermi al giorno prima senza alcun errore nel log.
"""
from __future__ import annotations

import fixtures as FX


class _Msg:
    """Il minimo che `_on_car_message` si aspetta da un messaggio paho."""

    def __init__(self, payload: dict) -> None:
        import json
        self.payload = json.dumps(payload).encode()
        self.topic = "app/1/test/account/msgCenter/msg"


async def _consegna(hass, coordinator, envelope: dict) -> None:
    """Consegna un envelope come farebbe il thread paho e attende la propagazione."""
    coordinator._on_car_message(None, None, _Msg(envelope))
    await hass.async_block_till_done()


def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def test_5a02_popola_i_campi(hass, integrazione_avviata):
    """Il push di telemetria riempie `fields` e marca l'auto come sveglia."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02(frontLeftDoor="1", doorLock="1"))

    campi = coord.data["fields"]
    assert campi["frontLeftDoor"] == "1"
    assert campi["doorLock"] == "1"
    assert coord.data["awake"] is True
    assert coord.data["last_seen"] is not None


async def test_il_campo_time_non_diventa_uno_stato(hass, integrazione_avviata):
    """`time` è il timestamp dell'envelope, non uno stato del veicolo."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02())
    assert "time" not in coord.data["fields"]


async def test_meta_di_conferma_fuori_dai_campi(hass, integrazione_avviata):
    """Una conferma comando porta `result`/`seq`/`resultTime`: sono meta del comando,
    non telemetria. I campi di STATO che l'accompagnano invece devono entrare."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.cmd_confirm(result="1"))

    campi = coord.data["fields"]
    for meta in ("result", "resultTime", "seq", "reason", "hasAsy"):
        assert meta not in campi, f"meta di conferma finito fra i campi: {meta}"
    assert campi["doorLock"] == "1", "i campi di stato della conferma devono entrare"


async def test_esito_conferma_leggibile(hass, integrazione_avviata):
    """L'esito mostrato all'utente distingue eseguito / in corso / fallito.

    `reason` valorizzato = guasto segnalato dall'auto, e vince su qualunque `result`:
    è l'unico campo che l'auto popola solo quando qualcosa è andato storto."""
    coord = _coordinator(hass, integrazione_avviata)

    await _consegna(hass, coord, FX.cmd_confirm(result="1"))
    assert "✅" in coord.data["cmd_status"]

    await _consegna(hass, coord, FX.cmd_confirm(result="5"))
    assert "⏳" in coord.data["cmd_status"]

    await _consegna(hass, coord, FX.cmd_confirm(result="1", reason=["door_open"]))
    assert "❌" in coord.data["cmd_status"], "un guasto non deve apparire come successo"


async def test_posizione_solo_dal_push_1301(hass, integrazione_avviata):
    """La posizione si riconosce dal TIPO di messaggio (1301), non dalla sola presenza
    di lat/lon: un 5A02 che per caso li contenesse non deve spostare il device_tracker."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.position_1301(lat=45.07, lon=7.68))

    assert coord.data["position"]["lat"] == "45.07"
    assert coord.data["last_pos_fix"] is not None

    # un 5A02 con lat/lon "di contrabbando" non deve essere trattato come posizione
    prima = coord.data["last_pos_fix"]
    await _consegna(hass, coord, FX.telemetry_5a02(lat="1.0", lon="2.0"))
    assert coord.data["position"]["lat"] == "45.07"
    assert coord.data["last_pos_fix"] == prima


async def test_solo_i_campi_geo_entrano_nella_posizione(hass, integrazione_avviata):
    """In `position` va SOLO la geolocalizzazione: batteria e simili vivono altrove."""
    coord = _coordinator(hass, integrazione_avviata)
    envelope = FX.position_1301()
    envelope["content"]["data"]["dumpEnergy"] = "72"
    await _consegna(hass, coord, envelope)
    assert "dumpEnergy" not in coord.data["position"]


async def test_payload_illeggibile_non_rompe_nulla(hass, integrazione_avviata):
    """Un messaggio corrotto deve essere ignorato: gira nel thread paho, un'eccezione
    lì dentro ucciderebbe la ricezione di tutti i messaggi successivi."""
    coord = _coordinator(hass, integrazione_avviata)

    class Rotto:
        payload = b"\xff\xfe non json"
        topic = "x"

    coord._on_car_message(None, None, Rotto())     # non deve sollevare
    await hass.async_block_till_done()
    assert coord.data is not None


async def test_serratura_zero_e_bloccata(hass, integrazione_avviata):
    """Convenzione verificata dal vivo (2026-06-17): doorLock 0 = Bloccata, 1 = Sbloccata.

    Era invertita in origine. Un'inversione qui è particolarmente insidiosa: la
    dashboard mostrerebbe "aperta" un'auto chiusa, o peggio il contrario."""
    from custom_components.omoda9.entity import field_on

    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02(doorLock="0"))
    assert coord.data["fields"]["doorLock"] == "0"
    assert field_on("0") is False
    assert field_on("1") is True
