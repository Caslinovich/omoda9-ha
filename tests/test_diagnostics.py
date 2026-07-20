"""«Scarica diagnostica»: il file che l'utente allega a una segnalazione.

È il pulsante che ogni utente ha nella pagina dell'integrazione, e l'intestazione di
`diagnostics.py` promette che il risultato sia sicuro da inviare. Questi test verificano
quella promessa — perché il 2026-07-20 non era vera: la posizione dell'auto usciva in
chiaro dentro `probe_status`, un messaggio DISCORSIVO in cui le coordinate erano scritte
nel testo («… lat=40.90…, lon=14.34… »), dove la redazione per nome di chiave non arriva.

La lezione è la stessa emersa col monitor: un dato sensibile va riconosciuto anche
**dalla forma**, non solo dal nome del campo che lo contiene.
"""
from __future__ import annotations

import json

import fixtures as FX

LAT, LON = 40.904308, 14.349437


async def _scarica(hass, entry) -> dict:
    from custom_components.omoda9.diagnostics import async_get_config_entry_diagnostics
    return await async_get_config_entry_diagnostics(hass, entry)


def _coord(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def test_le_coordinate_non_escono_da_un_messaggio_discorsivo(hass, integrazione_avviata):
    """La regressione vera, trovata leggendo un file di diagnostica reale."""
    coord = _coord(hass, integrazione_avviata)
    coord.data = {**coord.data,
                  "probe_status": (f"🟢 SVOLTA: dati realtime ricevuti! lat={LAT}, "
                                   f"lon={LON}, vehicleSpeed=0.0, odometer=4062")}

    blob = json.dumps(await _scarica(hass, integrazione_avviata))
    assert str(LAT) not in blob, "latitudine in chiaro nella diagnostica scaricabile"
    assert str(LON) not in blob, "longitudine in chiaro nella diagnostica scaricabile"
    # il resto del messaggio deve restare leggibile: serve a capire cosa è successo
    assert "odometer=4062" in blob


async def test_le_coordinate_non_escono_da_nessun_campo(hass, integrazione_avviata):
    """Non solo `probe_status`: qualunque campo di stato è un messaggio libero."""
    coord = _coord(hass, integrazione_avviata)
    coord.data = {**coord.data,
                  "cmd_status": f"posizione aggiornata a {LAT},{LON}",
                  "wake_status": f"auto trovata a {LAT}",
                  "session_detail": f"ok ({LON})"}

    blob = json.dumps(await _scarica(hass, integrazione_avviata))
    for pezzo in (str(LAT), str(LON)):
        assert pezzo not in blob, f"coordinata trapelata: {pezzo}"


async def test_realtime_senza_posizione(hass, integrazione_avviata):
    """Il payload realtime porta lat/lon come chiavi: quelle erano già coperte, e devono
    restarlo — qui si verifica che il fix non le abbia scoperte."""
    coord = _coord(hass, integrazione_avviata)
    coord.data = {**coord.data,
                  "realtime": {"lat": str(LAT), "lon": str(LON), "dumpEnergy": "68"}}

    blob = json.dumps(await _scarica(hass, integrazione_avviata))
    assert str(LAT) not in blob and str(LON) not in blob
    assert "68" in blob, "la telemetria utile è stata persa insieme alla posizione"


async def test_identita_e_segreti_non_escono(hass, integrazione_avviata):
    """Il resto della promessa dell'intestazione: né VIN, né email, né PIN, né token."""
    blob = json.dumps(await _scarica(hass, integrazione_avviata))
    for segreto, nome in ((FX.VIN, "VIN"), (FX.EMAIL, "email"), (FX.PIN, "PIN")):
        assert segreto not in blob, f"{nome} in chiaro nella diagnostica"
    assert "**REDACTED**" in blob, "la redazione non sembra aver fatto nulla"


async def test_la_diagnostica_resta_utile(hass, integrazione_avviata):
    """Il rovescio: oscurare tutto sarebbe inutile quanto non oscurare niente.
    Ciò che serve al supporto deve restare."""
    diag = await _scarica(hass, integrazione_avviata)
    stato = diag["coordinator"]["state"]
    assert "session_ok" in stato
    assert diag["coordinator"]["token_present"] in (True, False)
    assert diag["coordinator"]["certs_present"] is not None
