"""Binary sensor: porte/finestrini/cofano/baule (open) + comfort on/off + stato auto.

Lo stato fisico dell'auto (5A02) e la connettività sono in-memory nel coordinator →
dopo un riavvio di HA tornano `unknown`. I binary_sensor di stato sono RestoreEntity:
ripristinano l'ultimo on/off noto come fallback (parità col bridge, che persisteva via
MQTT retained) finché non arriva un dato live. Eccezione: `auto_sveglia` NON persiste
(è un flag derivato "l'auto sta pubblicando adesso" → al boot deve essere off).
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, FIELDS_AS_RICH_ENTITY
from .coordinator import SENSORS
from .entity import Omoda9Entity, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents = [
        Omoda9BinarySensor(coord, s)
        for s in SENSORS
        if s["comp"] == "binary_sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY
    ]
    ents.append(Omoda9Online(coord))
    ents.append(Omoda9Awake(coord))
    ents.append(Omoda9Session(coord))
    # — avvisi dal canale realtime (Round B): gomme + batteria scarica —
    for suffix, name, field, dc in _RT_BINARIES:
        ents.append(Omoda9RealtimeBinary(coord, name, suffix, field, dc))
    add(ents)


# Avvisi (warning) presenti sul canale realtime: ON = anomalia. `*TyreCall` = avviso
# pressione gomma (device_class PROBLEM); `socLowCall` = batteria di trazione scarica
# (device_class BATTERY → on = "low"). Convenzione ON/OFF (1=avviso) da confermare dal
# vivo. (suffix, nome, campo realtime, device_class)
_RT_BINARIES = [
    ("avviso_gomma_ant_sx", "Avviso gomma ant. SX", "lFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("avviso_gomma_ant_dx", "Avviso gomma ant. DX", "rFrontTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("avviso_gomma_post_sx", "Avviso gomma post. SX", "lRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("avviso_gomma_post_dx", "Avviso gomma post. DX", "rRearTyreCall", BinarySensorDeviceClass.PROBLEM),
    ("batteria_scarica", "Batteria scarica", "socLowCall", BinarySensorDeviceClass.BATTERY),
    # — 4 campi VERIFICATI dalla cattura live del payload realtime (2026-06-25, 91 campi:
    #   tutti presenti, ="0" a riposo). Sostituiscono i campi del bean SDK che la cattura ha
    #   dimostrato NON inviati da questa vettura (rimossi). —
    # oilCall = avviso carburante basso; electricityCall = avviso ricarica necessaria:
    # device_class PROBLEM (on = avviso). Polarità 1=avviso da confermare quando scatteranno.
    ("avviso_carburante_basso", "Avviso carburante basso", "oilCall", BinarySensorDeviceClass.PROBLEM),
    ("avviso_ricarica", "Avviso ricarica necessaria", "electricityCall", BinarySensorDeviceClass.PROBLEM),
    # engineState = motore termico in moto; hVoltageState = sistema alta tensione attivo.
    # device_class RUNNING (on = in funzione). A riposo entrambi 0 (verificato dal vivo).
    ("motore", "Motore acceso", "engineState", BinarySensorDeviceClass.RUNNING),
    ("alta_tensione", "Alta tensione attiva", "hVoltageState", BinarySensorDeviceClass.RUNNING),
]


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
        dc = spec.get("dclass")
        self._attr_device_class = BinarySensorDeviceClass(dc) if dc else None
        # campi che l'auto non invia mai da ferma (es. tendina tetto, risc. parabrezza):
        # restano sempre "unknown" → in categoria diagnostica, fuori dai controlli principali.
        if spec.get("diag"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _live_is_on(self) -> bool | None:
        # [MED] None/"None"/"" = assente → None (emerge il restored, non un falso off);
        # confronto numerico via field_on (allinea "0.0" con lock/switch/cover).
        return field_on(self.coordinator.data.get("fields", {}).get(self._key))


class Omoda9Online(_Omoda9RestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Connessione", "online")
        # entity_id PINNED allo storico `omoda9_connessa` (dashboard/automazioni non si rompono);
        # translation_key forzato a "connessa" per combaciare con la chiave in translations/*.json
        # (altrimenti la base la deriverebbe da "Connessione" → "connessione", chiave inesistente).
        self.entity_id = ENTITY_ID_FORMAT.format("omoda9_connessa")
        self._attr_translation_key = "connessa"

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt["onlineStatus"]) if "onlineStatus" in rt else None


class Omoda9RealtimeBinary(_Omoda9RestoreBinary):
    """Avviso generico su un campo del canale realtime (vedi `_RT_BINARIES`).

    Stesso pattern di `Omoda9Online` (legge da coordinator.data["realtime"]) ma in
    categoria diagnostica. ON se il campo è != 0; assente → ripristina l'ultimo noto."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, field: str,
                 device_class: BinarySensorDeviceClass) -> None:
        super().__init__(coord, f"Omoda9 {name}", f"rt_{suffix}")
        self._field = field
        self._attr_device_class = device_class

    def _live_is_on(self) -> bool | None:
        rt = self.coordinator.data.get("realtime") or {}
        return field_on(rt[self._field]) if self._field in rt else None


class Omoda9Awake(Omoda9Entity, BinarySensorEntity):
    """Flag derivato "l'auto sta pubblicando adesso" — NON persistente (off al boot)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Auto sveglia", "awake",
                         entity_id_format=ENTITY_ID_FORMAT)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("awake"))


class Omoda9Session(_Omoda9RestoreBinary):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Sessione", "session")

    def _live_is_on(self) -> bool | None:
        return self.coordinator.data.get("session_ok")
