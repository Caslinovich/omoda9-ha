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
# NB: «seq» sta qui perché nel payload realtime vale "<VIN>-<timestamp>" → contiene il VIN.
# NB: «certs_src» è il PERCORSO da cui l'utente ha importato i certificati mutual-TLS: è
# info-disclosure sul filesystem (nome utente, struttura delle cartelle, a volte un backup
# dell'app) e non serve al supporto → oscurato (P1-6).
TO_REDACT = {
    "email", "pin", "vin", "tuserid", "seq", "certs_src",
    "lat", "lon", "latitude", "longitude", "position",
}


def _scrub_vin(obj: Any, vin: str) -> Any:
    """Rete di sicurezza: toglie il VIN ovunque compaia come SOTTOSTRINGA, anche dentro un
    campo che la redazione per-chiave non conosce (es. un id composto)."""
    if not vin:
        return obj
    if isinstance(obj, dict):
        return {k: _scrub_vin(v, vin) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_vin(v, vin) for v in obj]
    if isinstance(obj, str) and vin in obj:
        return obj.replace(vin, "**REDACTED**")
    return obj


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
            # anche le options passano dalla redazione: oggi contengono solo intervalli di
            # polling, ma così una chiave sensibile aggiunta domani è già coperta.
            "options": async_redact_data(dict(entry.options), TO_REDACT),
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
    vin = getattr(coordinator, "vin", "") or ""
    # La posizione GPS è sensibile (dove abiti) → mai esportata, neanche oscurata coord-per-coord.
    realtime = data.get("realtime")
    if isinstance(realtime, dict):
        realtime = _scrub_vin(async_redact_data(realtime, TO_REDACT), vin)
    # Telemetria 5A02 (stato porte/clima/sedili…): redazione per chiave + passata anti-VIN.
    fields = data.get("fields")
    if isinstance(fields, dict):
        fields = _scrub_vin(async_redact_data(dict(fields), TO_REDACT), vin)

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
            "fields_count": len(data.get("fields") or {}),
            "fields": fields,
        },
    }

    # Monitor diagnostico (diag.py), presente solo se attivo: ring buffer + contatori.
    # Gli eventi sono GIÀ redatti alla cattura; qui passano comunque dalla redazione
    # standard — difesa in profondità, come per realtime/fields sopra.
    recorder = getattr(coordinator, "_diag", None)
    if recorder is not None:
        snap = recorder.snapshot()
        diag["diagnostic_mode"] = _scrub_vin(async_redact_data(snap, TO_REDACT), vin)

    return diag
