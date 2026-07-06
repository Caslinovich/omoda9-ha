"""Repair flow Omoda 9 — "PIN comandi errato": riconfigura il PIN a 4 cifre dei
comandi remoti senza smontare l'integrazione.

L'avviso viene creato dal coordinator (`_raise_pin_issue`) quando un comando fallisce
perché il backend rifiuta il taskId (PIN errato / anti-lockout). Il PIN NON serve al
login → correggerlo è pura scrittura in entry.data + reload: il reload azzera anche
l'anti-lockout module-level (`commands.reset_pin_lockout` in `_bind_core`)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import CONF_PIN


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
                return self.async_create_entry(title="", data={})
        schema = vol.Schema(
            {vol.Required(CONF_PIN, default=entry.data.get(CONF_PIN, "")): str}
        )
        return self.async_show_form(
            step_id="pin", data_schema=schema, errors=errors
        )
