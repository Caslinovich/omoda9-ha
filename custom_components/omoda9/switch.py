"""Switch: clima + comfort (sbrinamenti, volante, sedili).

Ogni interruttore fonde lo stato di sola lettura (un campo telemetria 5A02) con i due
comandi ON/OFF del catalogo in un'unica card: ON via app = funzione attivata (clima a
21°/sbrinamenti/sedili per ~15 min con timer auto-spegnimento dell'auto), OFF = comando
di spegnimento manuale. Il toggle ATTUA sull'auto (= consenso esplicito dell'utente).

I due sedili (riscaldamento / ventilazione guida) sono MUTUAMENTE ESCLUSIVI lato auto:
accendere l'aria spegne il caldo e viceversa (verificato in telemetria) → lo riflettiamo
subito anche nello stato ottimistico, oltre che dai campi reali quando arrivano.
"""
from __future__ import annotations

import ast

from homeassistant.components.switch import (
    ENTITY_ID_FORMAT,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import Omoda9Entity, Omoda9OptimisticMixin, field_on


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    # NB: il clima NON è più qui → è una climate entity (climate.py) con temperatura
    # impostabile. Restano comfort/sedili/sbrinamenti + i due switch ricarica EV.
    ricarica = Omoda9ChargeSwitch(coord)
    ricarica_prog = Omoda9ScheduledChargeSwitch(coord)
    parabrezza = Omoda9ComfortSwitch(
        coord, "Omoda9 Sbrinamento parabrezza", "frontWindshieldHeat", "frontWindshieldHeat",
        "defrost_parabrezza", "defrost_parabrezza_off", "mdi:car-defrost-front")
    lunotto = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento lunotto", "rWinHeatingState", "rWinHeatingState",
        "defrost_lunotto", "defrost_lunotto_off", "mdi:car-defrost-rear")
    volante = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento volante", "steerWheelHeating", "steerWheelHeating",
        "volante_caldo", "volante_caldo_off", "mdi:steering")
    sedile_caldo = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento sedile guida", "dSeatHeatingState", "dSeatHeatingState",
        "sedile_guida_caldo", "sedile_guida_caldo_off", "mdi:car-seat-heater")
    sedile_aria = Omoda9ComfortSwitch(
        coord, "Omoda9 Ventilazione sedile guida", "dSeatVentilateState", "dSeatVentilateState",
        "sedile_guida_aria", "sedile_guida_aria_off", "mdi:car-seat-cooler")
    # sedili passeggero e posteriori SX/DX: stesso modello del guida (telemetria *State*
    # ↔ comando seatControl). Posteriore centrale escluso (nessun comando dedicato).
    pass_caldo = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento sedile passeggero", "pSeatHeatingState", "pSeatHeatingState",
        "sedile_passeggero_caldo", "sedile_passeggero_caldo_off", "mdi:car-seat-heater")
    pass_aria = Omoda9ComfortSwitch(
        coord, "Omoda9 Ventilazione sedile passeggero", "pSeatVentilateState", "pSeatVentilateState",
        "sedile_passeggero_aria", "sedile_passeggero_aria_off", "mdi:car-seat-cooler")
    psx_caldo = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento sedile post. SX", "lSeatHeatingState2", "lSeatHeatingState2",
        "sedile_post_sx_caldo", "sedile_post_sx_caldo_off", "mdi:car-seat-heater")
    psx_aria = Omoda9ComfortSwitch(
        coord, "Omoda9 Ventilazione sedile post. SX", "lSeatVentilateState2", "lSeatVentilateState2",
        "sedile_post_sx_aria", "sedile_post_sx_aria_off", "mdi:car-seat-cooler")
    pdx_caldo = Omoda9ComfortSwitch(
        coord, "Omoda9 Riscaldamento sedile post. DX", "rSeatHeatingState2", "rSeatHeatingState2",
        "sedile_post_dx_caldo", "sedile_post_dx_caldo_off", "mdi:car-seat-heater")
    pdx_aria = Omoda9ComfortSwitch(
        coord, "Omoda9 Ventilazione sedile post. DX", "rSeatVentilateState2", "rSeatVentilateState2",
        "sedile_post_dx_aria", "sedile_post_dx_aria_off", "mdi:car-seat-cooler")
    # caldo e aria si escludono a vicenda su OGNI sedile → wiring reciproco per coppia
    for caldo, aria in ((sedile_caldo, sedile_aria), (pass_caldo, pass_aria),
                        (psx_caldo, psx_aria), (pdx_caldo, pdx_aria)):
        caldo._exclusive = aria
        aria._exclusive = caldo
    add([ricarica, ricarica_prog, parabrezza, lunotto, volante,
         sedile_caldo, sedile_aria, pass_caldo, pass_aria,
         psx_caldo, psx_aria, pdx_caldo, pdx_aria])


class Omoda9ComfortSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Interruttore comfort: ON se il campo 5A02 associato è != 0.

    Lo stato reale arriva via MQTT solo ad auto sveglia → dopo un comando si mostra
    subito lo stato target (ottimistico, vedi Omoda9OptimisticMixin) e al riavvio di
    HA si ripristina l'ultimo stato noto."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coord, name: str, suffix: str, field: str,
                 on_cmd: str, off_cmd: str, icon: str) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._field = field
        self._on_cmd = on_cmd
        self._off_cmd = off_cmd
        self._attr_icon = icon
        self._restored: bool | None = None
        self._exclusive: "Omoda9ComfortSwitch | None" = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_on(self) -> bool | None:
        return field_on(self.coordinator.data.get("fields", {}).get(self._field))

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_on()
        return live if live is not None else self._restored

    async def async_turn_on(self, **kwargs) -> None:
        # mutua esclusione: accendere questo spegne subito il gemello (es. aria↔caldo sedile)
        if self._exclusive is not None:
            self._exclusive._set_optimistic(False)
        await self._run_command(self._on_cmd, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command(self._off_cmd, False)


class Omoda9ChargeSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Ricarica IMMEDIATA on/off (chargeStartStopControl, controlType 1/0).

    Su questo canale l'auto NON pubblica uno stato "in ricarica" → lo switch è
    ottimistico: dopo il comando mostra subito il target e al riavvio ripristina
    l'ultimo stato noto. La spina collegata è il binary_sensor `Spina ricarica`."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:battery-charging"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Ricarica", "ricarica", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        return self._restored

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("ricarica_start", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("ricarica_stop", False)


class Omoda9ScheduledChargeSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Ricarica PROGRAMMATA on/off (chargeAppointControl, body con array annidato).

    Quando si accende, costruisce il piano dalle preferenze (number ora-inizio/durata,
    tutti i giorni) e invia mainSwitch=1 + piano attivo; spegnendo invia mainSwitch=0.
    Lo stato reale arriva dalla telemetria `chargeAppointPlans` (switchStatus del piano)."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Ricarica programmata", "ricarica_programmata",
                         entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    def _live_on(self) -> bool | None:
        raw = self.coordinator.data.get("fields", {}).get("chargeAppointPlans")
        if not raw:
            return None
        try:
            plans = ast.literal_eval(raw) if isinstance(raw, str) else raw
            if plans:
                return field_on(plans[0].get("switchStatus"))
        except (ValueError, SyntaxError, AttributeError, IndexError, TypeError):
            return None
        return None

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        live = self._live_on()
        return live if live is not None else self._restored

    def _plan(self, switch_status: int) -> dict:
        hour = int(getattr(self.coordinator, "charge_start_hour", 8) or 8)
        dur_h = int(getattr(self.coordinator, "charge_duration_hours", 6) or 6)
        return {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": hour * 60,
                "switchStatus": switch_status, "timeConsuming": dur_h * 60}

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_on", True,
                                {"mainSwitch": 1, "chargeAppointPlans": [self._plan(1)]})

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_off", False,
                                {"mainSwitch": 0, "chargeAppointPlans": [self._plan(0)]})
