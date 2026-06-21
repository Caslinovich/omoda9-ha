"""Custom component Omoda 9 / Jaecoo — bootstrap.

Sostituisce il bridge standalone (`ha_bridge.py`): la logica MQTT/REST vive in
`coordinator.py`, le entità sono native (niente più MQTT Discovery). Il "cuore di
protocollo" (auth, firma, comandi, sonda) è riusato da `core/` senza riscrivere
la logica già verificata sul campo.

⚠️ SCAFFOLD in costruzione: il config flow (OTP) è attivo; coordinator e platform
entità sono in via di completamento (vedi SHARING_TODO.md → roadmap component).
"""
from __future__ import annotations

import os
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS

# Vendor del "cuore di protocollo": i moduli in core/ si importano tra loro per
# nome (import wake / import omoda_auth as A …) → aggiungo core/ al path una volta.
_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inizializza l'integrazione da un config entry."""
    from .coordinator import Omoda9Coordinator

    coordinator = Omoda9Coordinator(hass, entry)

    # FASE 3c: i cert mutual-TLS devono esserci PRIMA di connettere l'MQTT auto.
    ok, detail = await coordinator.async_provision_certs()
    if not ok:
        raise ConfigEntryNotReady(detail)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # stato sessione iniziale + avvio connessione MQTT all'auto
    await coordinator.async_check_session()
    # [H4] se il connect MQTT iniziale fallisce, async_start solleva ConfigEntryNotReady:
    #      ripuliamo hass.data (niente coordinator appeso) e rilanciamo → HA ritenta il setup.
    try:
        await coordinator.async_start()
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await hass.async_add_executor_job(coordinator.async_stop)
        raise
    # keep-alive: refresh sessione periodico per non far scadere il token da fermi
    coordinator.async_start_keepalive()
    # poll telemetria periodico (sveglia + lettura); intervalli dalle opzioni
    coordinator.async_start_telemetry_poll()
    # ricarica l'entry quando l'utente cambia le opzioni (es. intervalli di poll)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opzioni cambiate → ricarica l'entry per riapplicare gli intervalli di poll."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica l'integrazione."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        # [MED] async_stop è bloccante (loop_stop fa join del thread paho) → executor,
        #       per non bloccare l'event loop durante l'unload.
        await hass.async_add_executor_job(coordinator.async_stop)
    return ok
