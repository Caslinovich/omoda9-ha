"""Device tracker: posizione GPS dell'auto (push 1301 / sonda realtime)."""
from __future__ import annotations

from homeassistant.components.device_tracker import (
    ENTITY_ID_FORMAT,
    SourceType,
    TrackerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([Omoda9Tracker(coord)])


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Omoda9Tracker(Omoda9Entity, TrackerEntity, RestoreEntity):
    """Posizione GPS. La posizione live è in-memory nel coordinator (push 1301 /
    sonda realtime) → dopo un riavvio di HA resta `unknown` finché non si preme
    «Localizza»/«Aggiorna posizione». Per non perdere la posizione sulla mappa,
    al boot si ripristina l'ultimo fix noto e lo si usa come fallback finché non
    arriva un dato live (il bridge otteneva lo stesso effetto via MQTT retained)."""

    _attr_icon = "mdi:car"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Posizione", "position",
                         entity_id_format=ENTITY_ID_FORMAT)
        self._restored_lat: float | None = None
        self._restored_lon: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._restored_lat = _f(last.attributes.get("latitude"))
            self._restored_lon = _f(last.attributes.get("longitude"))

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        live = _f(pos.get("lat") or pos.get("latitude"))
        return live if live is not None else self._restored_lat

    @property
    def longitude(self) -> float | None:
        pos = self.coordinator.data.get("position") or {}
        live = _f(pos.get("lon") or pos.get("longitude"))
        return live if live is not None else self._restored_lon
