"""Button: i comandi auto (catalogo core/commands) + sveglia + aggiorna posizione."""
from __future__ import annotations

import logging

from homeassistant.components.button import ENTITY_ID_FORMAT, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COMMANDS_AS_RICH_ENTITY, DOMAIN
from .entity import Omoda9Entity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    from .core import commands as CMD

    ents: list[ButtonEntity] = []
    for key, spec in CMD.COMMANDS:
        # i comandi che ora hanno un lock/switch/cover dedicato NON diventano pulsanti
        if key in COMMANDS_AS_RICH_ENTITY:
            continue
        ents.append(Omoda9CommandButton(coord, key, spec))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Sveglia auto", "wake", coord.async_wake))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Aggiorna posizione", "refresh_pos", coord.async_probe))
    # Aggiorna stato completo: forza odometro/batteria/tensione REALI accendendo brevemente il
    # clima (unico modo per accendere l'alta tensione, da cui dipendono i dati freschi).
    ents.append(Omoda9ActionButton(coord, "Omoda9 Aggiorna stato completo", "refresh_full",
                                    coord.async_refresh_full_status))
    # recupero sessione: azioni "di servizio" → categoria diagnostica (fuori dai controlli)
    ents.append(Omoda9ActionButton(coord, "Omoda9 Richiedi codice OTP", "otp_request",
                                    coord.async_request_otp, category=EntityCategory.DIAGNOSTIC))
    ents.append(Omoda9ActionButton(coord, "Omoda9 Conferma OTP", "otp_confirm",
                                    coord.async_confirm_otp, category=EntityCategory.DIAGNOSTIC))
    add(ents)


class Omoda9CommandButton(Omoda9Entity, ButtonEntity):
    """Un pulsante per comando del catalogo. Il tap = consenso esplicito all'attuazione."""

    def __init__(self, coord, key: str, spec: dict) -> None:
        # entity_id = button.omoda9_<key> (come il bridge), NON derivato dal nome lungo.
        super().__init__(coord, f"Omoda9 {spec['name']}", f"cmd_{key}",
                         object_id=f"omoda9_{key}", entity_id_format=ENTITY_ID_FORMAT)
        self._key = key
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    async def async_press(self) -> None:
        # [LOW] l'esito (anche di errore) è già pubblicato nei sensori diagnostici
        # (cmd_status) dal coordinator: qui logghiamo senza propagare un'eccezione grezza.
        try:
            await self.coordinator.async_send_command(self._key)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda9: comando «%s» non riuscito", self._key)


class Omoda9ActionButton(Omoda9Entity, ButtonEntity):
    """Pulsante per un'azione del coordinator (sveglia/sonda)."""

    _ICONS = {
        "wake": "mdi:car-connected",
        "refresh_pos": "mdi:crosshairs-gps",
        "refresh_full": "mdi:car-info",
        "otp_request": "mdi:email-fast",
        "otp_confirm": "mdi:check-decagram",
    }

    def __init__(self, coord, name: str, suffix: str, action, category=None) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._action = action
        self._attr_icon = self._ICONS.get(suffix, "mdi:gesture-tap-button")
        if category is not None:
            self._attr_entity_category = category

    async def async_press(self) -> None:
        # [LOW] sveglia/sonda/OTP: l'esito va nei sensori diagnostici; logga e non
        # propagare un'eccezione grezza nella UI.
        try:
            await self._action()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Omoda9: azione «%s» non riuscita", self._raw_name)
