"""Macro comfort «Raffredda/Riscalda tutto» e coda comandi.

Questi due test bloccano il difetto misurato in campo fra il 21 e il 31 luglio 2026 sui
cicli reali della macro: fra la pressione del tasto e la conferma dell'auto passavano
45-50 secondi, con l'interruttore già acceso e nulla di visibile. L'utente ripremeva, il
secondo ciclo si accavallava al primo e l'auto rifiutava con A00082 «veicolo occupato».

Le due cause sono indipendenti e vanno tenute ferme separatamente:

* la macro svegliava l'auto **anche quando era già desta**, pagando 35 secondi d'attesa
  per nulla (`test_macro_*`);
* la pausa che dovrebbe impedire a due comandi di accavallarsi si sbloccava al primo
  messaggio qualsiasi — e un'auto sveglia manda telemetria ogni pochi secondi, quindi la
  pausa durava mezzo secondo proprio quando serviva (`test_pausa_di_coda_*`).
"""
from __future__ import annotations

import asyncio

import fixtures as FX
import pytest

from custom_components.omoda9 import coordinator as coord_mod
from custom_components.omoda9 import switch as switch_mod
from custom_components.omoda9.const import DOMAIN

MACRO = "switch.omoda9_raffredda_tutto"


class _Msg:
    """Il minimo che `_on_car_message` si aspetta da un messaggio paho."""

    def __init__(self, payload: dict) -> None:
        import json
        self.payload = json.dumps(payload).encode()
        self.topic = "app/1/test/account/msgCenter/msg"


async def _consegna(hass, coordinator, envelope: dict) -> None:
    coordinator._on_car_message(None, None, _Msg(envelope))
    await hass.async_block_till_done()


def _coordinator(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]


@pytest.fixture
def comandi_inviati(monkeypatch):
    """Registra i comandi invece di mandarli all'auto, e azzera le attese della macro
    (nei test interessa la SEQUENZA, non i secondi)."""
    monkeypatch.setattr(switch_mod, "MACRO_WAKE_WAIT", 0)
    monkeypatch.setattr(switch_mod, "MACRO_WAKE_WAIT_AWAKE", 0)
    inviati: list[str] = []

    async def _finto(self, key, params=None):
        inviati.append(key)
        return "inviato (test)"

    monkeypatch.setattr(coord_mod.Omoda9Coordinator, "async_send_command", _finto)
    return inviati


async def test_macro_non_sveglia_un_auto_gia_sveglia(hass, integrazione_avviata,
                                                     comandi_inviati):
    """Auto che sta pubblicando → niente `localizza`: il bus comfort è già alimentato.

    Il `localizza` in più non era gratis: occupava uno slot della coda comandi e il
    comando vero partiva 35 secondi dopo, finestra in cui una seconda pressione mandava
    tutto in collisione."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02())   # ← l'auto parla: è sveglia
    assert coord.auto_sveglia is True

    await hass.services.async_call("switch", "turn_on", {"entity_id": MACRO},
                                   blocking=True)

    assert comandi_inviati == ["clima_raffredda_on"], (
        "ad auto desta la macro deve mandare SOLO il comando comfort")


async def test_macro_sveglia_un_auto_che_dorme(hass, integrazione_avviata,
                                               comandi_inviati):
    """Auto silenziosa → la sveglia resta obbligatoria, e prima del comando.

    È l'altra metà del fix: risparmiare i 35 secondi non deve trasformarsi nel saltare la
    sveglia a un'auto che dorme, dove i moduli comfort andrebbero tutti in timeout."""
    coord = _coordinator(hass, integrazione_avviata)
    coord._last_msg_ts = 0.0                            # ← nessun messaggio: dorme

    await hass.services.async_call("switch", "turn_on", {"entity_id": MACRO},
                                   blocking=True)

    assert comandi_inviati == ["localizza", "clima_raffredda_on"]


async def test_pausa_di_coda_ignora_la_telemetria(hass, integrazione_avviata,
                                                  monkeypatch):
    """La pausa fra due comandi finisce sulla CONFERMA, non su un messaggio qualsiasi.

    Era il difetto: `last_seen` avanza a ogni push, e un'auto sveglia ne manda uno ogni
    pochi secondi → la pausa scadeva subito e il comando successivo partiva a vettura
    ancora occupata (A00082)."""
    coord = _coordinator(hass, integrazione_avviata)
    monkeypatch.setattr(coord_mod, "COMMAND_SETTLE_S", 30)   # ampio: non deve mai scadere qui

    pausa = asyncio.create_task(coord._settle_after_command())
    await asyncio.sleep(0.2)

    await _consegna(hass, coord, FX.telemetry_5a02(dumpEnergy="61"))
    await asyncio.sleep(0.8)
    assert not pausa.done(), "la telemetria non è una conferma: la pausa deve proseguire"

    await _consegna(hass, coord, FX.cmd_confirm(result="1"))
    await asyncio.sleep(0.8)
    assert pausa.done(), "arrivata la conferma, il comando successivo può partire"
    await pausa


async def test_pausa_di_coda_ha_comunque_un_tetto(hass, integrazione_avviata,
                                                  monkeypatch):
    """Se la conferma non arriva MAI (auto che si riaddormenta, push perso) la pausa
    deve scadere da sola: un comando in coda non può restare appeso per sempre."""
    coord = _coordinator(hass, integrazione_avviata)
    monkeypatch.setattr(coord_mod, "COMMAND_SETTLE_S", 1)

    await asyncio.wait_for(coord._settle_after_command(), timeout=5)
