"""Repair flow Omoda 9 — "PIN comandi errato": riconfigura il PIN a 4 cifre dei
comandi remoti senza smontare l'integrazione.

L'avviso viene creato dal coordinator (`_raise_pin_issue`) quando un comando fallisce
perché il backend rifiuta il taskId (PIN errato / anti-lockout). Il PIN NON serve al
login → correggerlo è pura scrittura in entry.data + reload, seguito dall'azzeramento
esplicito dell'anti-lockout di quel veicolo (vedi `_clear_pin_lockout`)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_PIN, DOMAIN


def _clear_pin_lockout(hass: HomeAssistant, entry_id: str) -> None:
    """P0-2: azzera INCONDIZIONATAMENTE anti-lockout + taskId in cache del veicolo.

    Il reset avviene anche se l'utente riconferma lo STESSO PIN: il blocco poteva non
    essere colpa del PIN, e senza reset i comandi continuerebbero a fallire in silenzio
    fino allo scadere della finestra. Qui l'utente ha compiuto un gesto esplicito di
    rimedio → si riparte sempre puliti.

    P2-6: lo stato è per-veicolo (nel `CoreCtx` del coordinator), non più un global
    condiviso da tutte le auto configurate."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is not None:
        coordinator.ctx.reset_pin_lockout()


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Factory richiesta da HA per l'avviso `pin_wrong`."""
    return Omoda9PinRepairFlow(data or {})


class Omoda9PinRepairFlow(RepairsFlow):
    """Chiede il nuovo PIN comandi e lo applica all'entry (poi reload)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._entry_id: str | None = data.get("entry_id")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_pin()

    async def async_step_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        entry = (
            self.hass.config_entries.async_get_entry(self._entry_id)
            if self._entry_id
            else None
        )
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        errors: dict[str, str] = {}
        if user_input is not None:
            new_pin = (user_input.get(CONF_PIN) or "").strip()
            if not new_pin:
                errors["base"] = "pin_required"
            else:
                # scrivi il nuovo PIN e ricarica: _bind_core rileva il cambio e azzera
                # l'anti-lockout; il completamento del fix flow rimuove l'avviso.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_PIN: new_pin}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                # P0-2: reset incondizionato, anche se il PIN reinserito è identico.
                # Dopo il reload, così agisce sul coordinator ricreato.
                _clear_pin_lockout(self.hass, entry.entry_id)
                return self.async_create_entry(title="", data={})
        # P1-5: campo PASSWORD, nessun default col PIN attuale (credenziale in chiaro nel form).
        schema = vol.Schema(
            {
                vol.Required(CONF_PIN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }
        )
        return self.async_show_form(
            step_id="pin", data_schema=schema, errors=errors
        )
