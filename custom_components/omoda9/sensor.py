"""Sensor: serratura (lock), livelli sedili (level) + batteria/velocità/sessione
+ sensori diagnostici del ponte (esiti comando/sveglia/sonda, timestamp).

Gli entity_id riproducono 1:1 quelli del bridge (omoda9_*) per continuità storico.
Tutti i sensori sono RestoreSensor: al riavvio di HA ripristinano l'ultimo valore
noto come fallback (parità col bridge, che persisteva via MQTT retained) finché non
arriva un dato live dall'auto.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    RestoreSensor,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SENSORS
from .entity import Omoda9Entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents: list = [
        Omoda9FieldSensor(coord, s) for s in SENSORS if s["comp"] == "sensor"
    ]
    ents.append(Omoda9Battery(coord))
    ents.append(Omoda9Speed(coord))
    ents.append(Omoda9SessionStatus(coord))
    # — sensori diagnostici (parità col bridge) —
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito comando", "cmd_status", "cmd_status", "mdi:car-cog"))
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito sveglia", "wake_status", "wake_status", "mdi:car-connected"))
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito sonda posizione", "probe_status", "probe_status", "mdi:crosshairs-gps"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultimo contatto", "lastseen", "last_seen", "mdi:car-clock"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultima sveglia", "wake_ts", "last_wake", "mdi:car-clock"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultima posizione", "pos_fix", "last_pos_fix", "mdi:map-marker-clock"))
    add(ents)


class _Omoda9RestoreSensor(Omoda9Entity, RestoreSensor):
    """Base sensore Omoda 9 che sopravvive al riavvio di HA.

    Lo stato (telemetria 5A02, realtime, diagnostica) è in-memory nel coordinator
    → dopo un restart torna `unknown`. Qui ripristiniamo l'ultimo valore noto e lo
    usiamo come fallback finché non arriva un dato live. Le sottoclassi forniscono
    `_live_value()` (valore corrente dal coordinator, o None se assente)."""

    def __init__(self, coord, name: str, unique_suffix: str) -> None:
        super().__init__(coord, name, unique_suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._restored = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None:
            self._restored = last.native_value

    def _live_value(self):
        """Sottoclassi: valore corrente dal coordinator, o None se assente."""
        raise NotImplementedError

    @property
    def native_value(self):
        live = self._live_value()
        return live if live is not None else self._restored


class Omoda9FieldSensor(_Omoda9RestoreSensor):
    """serratura (0=Bloccata/1=Sbloccata) o livello sedile (Livello N)."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda9 {spec['name']}", spec["key"])
        self._key = spec["key"]
        self._kind = spec["kind"]
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    def _live_value(self):
        v = self.coordinator.data.get("fields", {}).get(self._key)
        if v is None:
            return None
        if self._kind == "lock":
            return "Bloccata" if str(v) in ("0", "0.0") else "Sbloccata"
        if self._kind == "level":
            return f"Livello {v}"
        return str(v)


class Omoda9Battery(_Omoda9RestoreSensor):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Batteria", "battery")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        try:
            return float(rt["dumpEnergy"]) if "dumpEnergy" in rt else None
        except (TypeError, ValueError):
            return None


class Omoda9Speed(_Omoda9RestoreSensor):
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_icon = "mdi:speedometer"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Velocità", "speed")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        try:
            return float(rt["vehicleSpeed"]) if "vehicleSpeed" in rt else None
        except (TypeError, ValueError):
            return None


class Omoda9SessionStatus(_Omoda9RestoreSensor):
    _attr_icon = "mdi:key-chain"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Stato sessione", "session_detail")

    def _live_value(self):
        return self.coordinator.data.get("session_detail") or None


class Omoda9TextSensor(_Omoda9RestoreSensor):
    """Sensore testuale diagnostico (esito ultimo comando/sveglia/sonda)."""

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str) -> None:
        super().__init__(coord, name, suffix)
        self._data_key = data_key
        self._attr_icon = icon

    def _live_value(self):
        return self.coordinator.data.get(self._data_key) or None


class Omoda9TimestampSensor(_Omoda9RestoreSensor):
    """Timestamp diagnostico (ultimo contatto/sveglia/posizione)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str) -> None:
        super().__init__(coord, name, suffix)
        self._data_key = data_key
        self._attr_icon = icon

    def _live_value(self):
        return self.coordinator.data.get(self._data_key)
