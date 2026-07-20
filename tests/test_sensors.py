"""Sensori realtime: quando un valore va tenuto e quando deve sparire.

I sensori Omoda sopravvivono al riavvio di HA tenendo l'ultimo valore noto — giusto per
l'odometro o la batteria, che restano veri anche se una singola lettura non li contiene.
Ma non per tutto: «Tempo di ricarica residuo» ha senso SOLO mentre l'auto carica. Quando
la carica finisce il campo sparisce dal payload, ed è proprio quello il segnale che deve
diventare «sconosciuto». Restava invece a 120 min per ore (trovato in campo il 2026-07-20).
"""
from __future__ import annotations

import json


def _coord(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


class _Msg:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
        self.topic = "x"


async def _push_realtime(hass, coord, rt: dict) -> None:
    """Simula una lettura realtime (il canale sonda), che aggiorna coord.data['realtime']."""
    coord._on_probe_data(rt)
    await hass.async_block_till_done()


# Una lettura realtime porta SEMPRE l'insieme completo dei campi (~91). L'unico che
# compare o sparisce a seconda dello stato è `remainChargeTime`: presente mentre l'auto
# carica, assente altrimenti. I due test simulano proprio quella transizione.
_IN_CARICA = {"odometer": "4062", "dumpEnergy": "68", "totalVoltage": "350.3",
              "remainChargeTime": "120", "chargeState": "1"}
_A_RIPOSO = {"odometer": "4062", "dumpEnergy": "80", "totalVoltage": "0",
             "chargeState": "0"}   # NB: senza remainChargeTime


def _entita(hass, entity_id):
    """L'OGGETTO entità (non solo lo stato), per manipolarne lo stato ripristinato."""
    comp = hass.data["entity_components"]["sensor"]
    return next(e for e in comp.entities if e.entity_id == entity_id)


async def test_tempo_ricarica_sparisce_a_carica_finita(hass, integrazione_avviata):
    """Il fix: a carica finita il campo non arriva più → il sensore torna a «sconosciuto»,
    non resta inchiodato ai 120 min dell'ultima carica.

    Il dettaglio che fa la differenza: si imposta `_restored` = 120, cioè lo scenario di
    PRODUZIONE (HA riavviato mentre l'auto caricava salva 120 come ultimo valore). Senza
    questo il test passerebbe anche col bug, perché nell'ambiente di test non c'è valore
    ripristinato ed è proprio quel valore che il difetto teneva inchiodato."""
    coord = _coord(hass, integrazione_avviata)
    ent = "sensor.omoda9_tempo_di_ricarica_residuo"
    _entita(hass, ent)._restored = 120.0     # come dopo un riavvio in carica

    await _push_realtime(hass, coord, _IN_CARICA)
    assert hass.states.get(ent).state == "120.0"

    await _push_realtime(hass, coord, _A_RIPOSO)
    stato = hass.states.get(ent).state
    assert stato in ("unknown", "unavailable"), (
        f"«Tempo di ricarica residuo» è rimasto a {stato} dopo la fine della carica"
    )


async def test_gli_altri_sensori_non_spariscono_a_fine_carica(hass, integrazione_avviata):
    """Il rovescio: la stessa transizione NON deve azzerare odometro e batteria, che
    nella lettura a riposo ci sono ancora. Solo il tempo di ricarica è volatile."""
    coord = _coord(hass, integrazione_avviata)

    await _push_realtime(hass, coord, _IN_CARICA)
    await _push_realtime(hass, coord, _A_RIPOSO)

    assert hass.states.get("sensor.omoda9_odometro").state == "4062.0"
    assert hass.states.get("sensor.omoda9_batteria").state == "80.0"


async def test_un_solo_sensore_e_volatile(hass, integrazione_avviata):
    """Guard-rail: rendere volatile un sensore che non lo è lo farebbe sparire a ogni
    lettura parziale. Oggi solo il tempo di ricarica lo è."""
    from custom_components.omoda9.sensor import _RT_SENSORS

    vol = [s.field for s in _RT_SENSORS if s.volatile]
    assert vol == ["remainChargeTime"], f"sensori volatili inattesi: {vol}"
