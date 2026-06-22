"""Diagnostica scaricabile dell'integrazione Omoda 9 / Jaecoo.

Genera il report che HA offre con «Scarica diagnostica» nella pagina
dell'integrazione. Pensato per il SUPPORTO: contiene stato sessione, parametri
di regione, presenza di token/certificati e l'ultima telemetria ricevuta, ma
NON espone alcun dato personale o segreto:

  • email, PIN, VIN, tUserId            → oscurati (REDACTED)
  • posizione GPS (lat/lon)             → oscurata (dove vivi non esce mai)
  • token e certificati mutual-TLS      → solo «presente: sì/no», mai il contenuto

Così l'utente può inviarti il file in tutta sicurezza.
"""
from __future__ import annotations

import os
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CERT_FILES

# Chiavi da oscurare ovunque compaiano (config entry + eventuali dict annidati).
TO_REDACT = {
    "email", "pin", "vin", "tuserid",
    "lat", "lon", "latitude", "longitude", "position",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Report diagnostico per un config entry (richiamato da «Scarica diagnostica»)."""
    diag: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            # titolo forzato senza VIN (il titolo reale è "Omoda 9 (<VIN>)")
            "title": "Omoda 9",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
    }

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        diag["coordinator"] = "non inizializzato (entry non caricato)"
        return diag

    # Presenza dei file sensibili come semplici booleani — mai il loro contenuto.
    token_present = await hass.async_add_executor_job(
        os.path.isfile, coordinator.token_path
    )
    certs_present: dict[str, bool] = {}
    for fname in CERT_FILES:
        path = os.path.join(coordinator.certs_dir, fname)
        certs_present[fname] = await hass.async_add_executor_job(os.path.isfile, path)

    data = dict(coordinator.data or {})
    has_position = bool(data.get("position"))
    # La posizione GPS è sensibile (dove abiti) → mai esportata, neanche oscurata coord-per-coord.
    realtime = data.get("realtime")
    if isinstance(realtime, dict):
        realtime = async_redact_data(realtime, TO_REDACT)

    diag["coordinator"] = {
        "region": {
            "bff": coordinator.bff,
            "tsp_host": coordinator.tsp_host,
            "car_mqtt_host": coordinator.car_host,
            "car_mqtt_port": coordinator.car_port,
            "channel_id": coordinator.channel_id,
        },
        "poll": {
            "normal_min": coordinator.poll_normal_min,
            "charging_min": coordinator.poll_charging_min,
            "enabled": coordinator.poll_enabled,
        },
        "token_present": token_present,
        "certs_present": certs_present,
        "state": {
            "session_ok": data.get("session_ok"),
            "session_detail": data.get("session_detail"),
            "awake": data.get("awake"),
            "car_connected": data.get("car_connected"),
            "has_position_fix": has_position,
            "last_seen": data.get("last_seen"),
            "last_wake": data.get("last_wake"),
            "last_pos_fix": data.get("last_pos_fix"),
            "cmd_status": data.get("cmd_status"),
            "wake_status": data.get("wake_status"),
            "probe_status": data.get("probe_status"),
            "realtime": realtime,
            # Telemetria 5A02 (stato porte/clima/sedili…): utile al debug, non è un dato personale.
            "fields_count": len(data.get("fields") or {}),
            "fields": data.get("fields"),
        },
    }
    return diag
