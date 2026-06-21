"""Number: parametri di configurazione locali (non comandi diretti all'auto).

Questi cursori NON inviano nulla all'auto da soli: memorizzano le preferenze usate
dagli altri controlli al momento dell'invio.
  - Durata clima (min): durata `times` del comando airControl della climate entity.
  - Ricarica programmata · ora di inizio e durata (ore): compongono il piano
    `chargeAppointControl` quando si accende lo switch "Ricarica programmata".

Sono RestoreNumber → al riavvio di HA ripristinano l'ultimo valore impostato e lo
riscrivono sul coordinator (da cui climate/switch lo leggono).
"""
from __future__ import annotations

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import Omoda9Entity

# (nome, suffix, attributo sul coordinator, min, max, step, default, unità, icona)
NUMBERS = [
    ("Omoda9 Durata clima", "clima_durata", "clima_duration",
     5, 30, 5, 15, UnitOfTime.MINUTES, "mdi:timer-cog"),
    ("Omoda9 Ricarica · ora di inizio", "ricarica_ora_inizio", "charge_start_hour",
     0, 23, 1, 8, UnitOfTime.HOURS, "mdi:clock-start"),
    ("Omoda9 Ricarica · durata", "ricarica_durata_ore", "charge_duration_hours",
     1, 12, 1, 6, UnitOfTime.HOURS, "mdi:battery-clock"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([Omoda9ConfigNumber(coord, *spec) for spec in NUMBERS])


class Omoda9ConfigNumber(Omoda9Entity, RestoreNumber):
    """Cursore di configurazione locale: scrive il proprio valore sul coordinator."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, name, suffix, attr, vmin, vmax, step, default, unit, icon) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._attr = attr
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._value = float(default)
        setattr(coord, attr, default)   # default subito disponibile ai consumatori

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._value = float(last.native_value)
        self._push()

    def _push(self) -> None:
        # mantieni il valore come int quando è intero (orari/giorni), così i body comando
        # non finiscono con "8.0" dove l'app usa interi.
        v = int(self._value) if float(self._value).is_integer() else self._value
        setattr(self.coordinator, self._attr, v)

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self._push()
        self.async_write_ha_state()
