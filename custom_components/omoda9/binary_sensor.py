"""Binary sensor: porte/finestrini/cofano/baule (open) + comfort on/off + stato auto.

Lo stato fisico dell'auto (5A02) e la connettività sono in-memory nel coordinator →
dopo un riavvio di HA tornano `unknown`. I binary_sensor di stato sono RestoreEntity:
ripristinano l'ultimo on/off noto come fallback (parità col bridge, che persisteva via
MQTT retained) finché non arriva un dato live. Eccezione: `auto_sveglia` NON persiste
(è un flag derivato "l'auto sta pubblicando adesso" → al boot deve essere off).
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import ENTITY_ID_FORMAT, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import SENSORS
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [Omoda9BinarySensor(coord, s) for s in SENSORS if s["comp"] == "binary_sensor"]
    ents.append(Omoda9Online(coord))
    ents.append(Omoda9Awake(coord))
    ents.append(Omoda9Session(coord))
    add(ents)


class _Omoda9RestoreBinary(Omoda9Entity, BinarySensorEntity, RestoreEntity):
    """Binary sensor che ripristina l'ultimo stato on/off al riavvio di HA.

    Le sottoclassi forniscono `_live_is_on()` (stato corrente dal coordinator, o
    None se assente); finché il live è None si usa l'ultimo valore ripristinato."""

    def __init__(self, coord, name: str, unique_suffix: str) -> None:
        super().__init__(coord, name, unique_suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_is_on(self) -> bool | None:
        raise NotImplementedError

    @property
    def is_on(self) -> bool | None:
        live = self._live_is_on()
        return live if live is not None else self._restored


class Omoda9BinarySensor(_Omoda9RestoreBinary):
    """ON se il campo è != 0 (open/onoff)."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda9 {spec['name']}", spec["key"])
        self._key = spec["key"]
        self._attr_device_class = spec.get("dclass")

    def _live_is_on(self) -> bool | None:
        v = self.coordinator.data.get("fields", {}).get(self._key)
        if v is None:
            return None
        return str(v) not in ("0", "", "None", "false", "False")


class Omoda9Online(_Omoda9RestoreBinary):
    _attr_device_class = "connectivity"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Connessa", "online")

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        if "onlineStatus" in rt:
            return str(rt["onlineStatus"]) not in ("0", "", "None")
        return None


class Omoda9Awake(Omoda9Entity, BinarySensorEntity):
    """Flag derivato "l'auto sta pubblicando adesso" — NON persistente (off al boot)."""

    _attr_device_class = "running"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Auto sveglia", "awake",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("awake"))


class Omoda9Session(_Omoda9RestoreBinary):
    _attr_device_class = "connectivity"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Sessione", "session")

    def _live_is_on(self) -> bool | None:
        return self.coordinator.data.get("session_ok")
