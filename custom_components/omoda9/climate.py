"""Climate: clima avanzato Omoda 9 (preclimatizzazione con temperatura impostabile).

Sostituisce il vecchio interruttore clima a 21° fisso: ora si imposta la temperatura
desiderata (16–30 °C) e l'auto la applica (riscalda o raffredda fino al setpoint).
Usa il comando `airControl` (lo stesso, verificato dal vivo, che faceva partire il
clima fisso), variando `temperature` e la durata `times` (da number.omoda9_clima_durata).

Modello HA: un'unica climate entity con modi OFF / HEAT_COOL (= l'auto porta l'abitacolo
al setpoint scaldando o raffreddando) + un solo cursore di temperatura. Lo stato
acceso/spento arriva dalla telemetria `frontHVACState`; dopo un comando si mostra subito
lo stato target (ottimistico) finché non arriva un nuovo dato dall'auto.

I sedili riscaldati/ventilati e gli sbrinamenti restano interruttori separati (switch.py):
così accendere il clima NON tocca lo stato dei sedili.
"""
from __future__ import annotations

from homeassistant.components.climate import (
    ENTITY_ID_FORMAT,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import Omoda9Entity, field_on

MIN_TEMP = 16.0
MAX_TEMP = 30.0
DEFAULT_TEMP = 21.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    add([Omoda9Climate(coord)])


class Omoda9Climate(Omoda9Entity, ClimateEntity, RestoreEntity):
    """Clima dell'auto: ON (HEAT_COOL) al setpoint scelto / OFF, via airControl."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1.0
    _attr_icon = "mdi:air-conditioner"
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coord) -> None:
        # entity_id FORZATO a climate.omoda9_clima (come le altre entità del componente,
        # altrimenti HA lo deriva "sporco" col nome device: climate.omoda_9_omoda9_clima).
        # unique_id distinto dal vecchio switch (suffix "climate") → entità nuova, non rename.
        super().__init__(coord, "Omoda9 Clima", "climate", entity_id_format=ENTITY_ID_FORMAT)
        self._target = DEFAULT_TEMP
        self._opt_on: bool | None = None
        self._opt_anchor = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            t = last.attributes.get(ATTR_TEMPERATURE)
            try:
                if t is not None:
                    self._target = min(MAX_TEMP, max(MIN_TEMP, float(t)))
            except (TypeError, ValueError):
                pass

    # ── stato ──
    def _live_on(self) -> bool | None:
        return field_on(self.coordinator.data.get("fields", {}).get("frontHVACState"))

    @property
    def target_temperature(self) -> float:
        return self._target

    @property
    def hvac_mode(self) -> HVACMode:
        on = self._opt_on
        if on is None:
            on = self._live_on()
        return HVACMode.HEAT_COOL if on else HVACMode.OFF

    def _handle_coordinator_update(self) -> None:
        # un nuovo messaggio dall'auto (last_seen cambiato) invalida l'ottimismo
        if self._opt_on is not None and \
                self.coordinator.data.get("last_seen") != self._opt_anchor:
            self._opt_on = None
            self._opt_anchor = None
        super()._handle_coordinator_update()

    def _set_optimistic(self, on: bool) -> None:
        self._opt_on = on
        self._opt_anchor = self.coordinator.data.get("last_seen")
        self.async_write_ha_state()

    # ── comandi ──
    def _params(self) -> dict:
        dur = int(getattr(self.coordinator, "clima_duration", 15) or 15)
        return {"temperature": f"{self._target:.1f}", "times": str(dur)}

    async def _send(self, key: str, on: bool) -> None:
        self._set_optimistic(on)
        try:
            await self.coordinator.async_send_command(key, self._params())
        except Exception as err:  # noqa: BLE001
            self._opt_on = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"Comando clima non riuscito: {err}") from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._send("clima_off", False)
        else:
            await self._send("clima_on", True)

    async def async_turn_on(self) -> None:
        await self._send("clima_on", True)

    async def async_turn_off(self) -> None:
        await self._send("clima_off", False)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        self._target = min(MAX_TEMP, max(MIN_TEMP, float(temp)))
        # se il clima è già acceso, riapplica subito il nuovo setpoint; altrimenti
        # memorizza soltanto (verrà usato alla prossima accensione).
        if self.hvac_mode != HVACMode.OFF:
            await self._send("clima_on", True)
        else:
            self.async_write_ha_state()
