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
import asyncio

from homeassistant.components.switch import (
    ENTITY_ID_FORMAT,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, MACRO_WAKE_WAIT, MACRO_PRESET_S
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
    # macro comfort "tutto" (coolingControl/heatingControl): clima + tutti i sedili (+ volante
    # e sbrinatori per il caldo) in un unico comando, come l'app. Funzionano a auto SPENTA.
    # Raffredda e riscalda si escludono a vicenda.
    raffredda = Omoda9ClimaMacroSwitch(
        coord, "Omoda9 Raffredda tutto", "raffredda_tutto",
        "clima_raffredda_on", "clima_raffredda_off", "mdi:snowflake")
    riscalda = Omoda9ClimaMacroSwitch(
        coord, "Omoda9 Riscalda tutto", "riscalda_tutto",
        "clima_riscalda_on", "clima_riscalda_off", "mdi:heat-wave")
    raffredda._exclusive = riscalda
    riscalda._exclusive = raffredda
    antifurto = Omoda9TheftAlarmSwitch(coord)
    polling = Omoda9PollingSwitch(coord)
    add([ricarica, ricarica_prog, parabrezza, lunotto, volante,
         sedile_caldo, sedile_aria, pass_caldo, pass_aria,
         psx_caldo, psx_aria, pdx_caldo, pdx_aria,
         raffredda, riscalda, antifurto, polling])


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


class Omoda9ClimaMacroSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Macro clima "tutto" (coolingControl/heatingControl): un preset che accende clima +
    TUTTI i sedili (+ sbrinatori parabrezza/lunotto e volante per il caldo) in un colpo solo,
    con un unico comando — esattamente come l'app ufficiale.

    ⚠️ I moduli comfort (clima+sedili) rispondono SOLO a vettura desta e con i sistemi
    alimentati. Premendo la macro a auto dormiente (parcheggiata da poco) tutti i moduli vanno
    in timeout. Perciò la macro SVEGLIA prima l'auto (localizza/vehicleLocation) e ATTENDE
    MACRO_WAKE_WAIT secondi che la TBOX alimenti il bus comfort, POI invia il comando — su
    ENTRAMBE le direzioni (anche lo spegnimento sveglia, così "tutto OFF" arriva ai sedili
    posteriori, che sono indipendenti dal clima). Verificato dal vivo 2026-06-21.

    Stato: l'auto NON pubblica uno stato "preset attivo" dedicato → interruttore a stato
    proprio (ottimistico PERSISTENTE: non viene azzerato dai messaggi telemetria, altrimenti
    non si potrebbe spegnere). Si auto-spegne da solo dopo MACRO_PRESET_S (l'auto chiude il
    preset dopo ~15 min). Raffredda e Riscalda si escludono a vicenda."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coord, name: str, suffix: str,
                 on_cmd: str, off_cmd: str, icon: str) -> None:
        super().__init__(coord, name, suffix, entity_id_format=ENTITY_ID_FORMAT)
        self._on_cmd = on_cmd
        self._off_cmd = off_cmd
        self._attr_icon = icon
        self._restored: bool | None = None
        self._expire_unsub = None
        self._exclusive: "Omoda9ClimaMacroSwitch | None" = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_expire()
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        return bool(self._restored)

    def _handle_coordinator_update(self) -> None:
        # macro SENZA stato reale dall'auto → NON azzerare lo stato sui messaggi telemetria
        # (il mixin lo farebbe): manteniamo lo stato impostato, aggiorniamo solo la UI.
        self.async_write_ha_state()

    def _cancel_expire(self) -> None:
        if self._expire_unsub is not None:
            self._expire_unsub()
            self._expire_unsub = None

    @callback
    def _set_state(self, value: bool) -> None:
        self._set_optimistic(value)
        self._restored = value

    async def _wake_then(self, cmd: str, target: bool) -> None:
        """Sveglia l'auto, attende che i moduli comfort siano alimentati, poi invia il comando.
        I due invii passano dalla coda comandi del coordinator (uno alla volta, in ordine)."""
        self._cancel_expire()
        self._set_state(target)
        # sveglia (vehicleLocation = sveglia + GPS, benigno); non bloccare la macro se fallisce
        try:
            await self.coordinator.async_send_command("localizza")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(MACRO_WAKE_WAIT)  # lascia accendere il bus comfort
        try:
            await self.coordinator.async_send_command(cmd)
        except Exception as err:  # noqa: BLE001
            self._set_state(False)
            self.async_write_ha_state()
            raise HomeAssistantError(f"Comando «{cmd}» non riuscito: {err}") from err
        if target:
            # l'auto chiude il preset dopo ~15 min → riporta lo switch a OFF da solo
            @callback
            def _expire(_now) -> None:
                self._expire_unsub = None
                self._set_state(False)
                self.async_write_ha_state()
            self._expire_unsub = async_call_later(self.hass, MACRO_PRESET_S, _expire)

    async def async_turn_on(self, **kwargs) -> None:
        if self._exclusive is not None:
            self._exclusive._cancel_expire()
            self._exclusive._set_state(False)
            self._exclusive.async_write_ha_state()
        await self._wake_then(self._on_cmd, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._wake_then(self._off_cmd, False)


class Omoda9ScheduledChargeSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Ricarica PROGRAMMATA on/off (chargeAppointControl, body con array annidato).

    Quando si accende, costruisce il piano dalle preferenze (entità time "orario di
    inizio" + number "durata", tutti i giorni) e invia mainSwitch=1 + piano attivo;
    spegnendo invia mainSwitch=0. startTime è in MINUTI dalla mezzanotte (verificato dal
    vivo: 465 = 07:45). Lo stato reale arriva dalla telemetria `chargeAppointPlans`."""

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
        # orario di inizio in minuti-da-mezzanotte dall'entità time; fallback al vecchio
        # cursore ore (compat) e infine 08:00 se nessuna preferenza è ancora disponibile.
        mins = getattr(self.coordinator, "charge_start_minutes", None)
        if mins is None:
            mins = int(getattr(self.coordinator, "charge_start_hour", 8) or 8) * 60
        dur_h = int(getattr(self.coordinator, "charge_duration_hours", 6) or 6)
        return {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": int(mins),
                "switchStatus": switch_status, "timeConsuming": dur_h * 60}

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_on", True,
                                {"mainSwitch": 1, "chargeAppointPlans": [self._plan(1)]})

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("ricarica_prog_off", False,
                                {"mainSwitch": 0, "chargeAppointPlans": [self._plan(0)]})


class Omoda9PollingSwitch(Omoda9Entity, SwitchEntity, RestoreEntity):
    """Interruttore "Aggiornamento automatico": attiva/disattiva il poll periodico
    (sveglia + lettura) senza toccare le opzioni. NON è un comando all'auto: agisce solo
    sul timer locale. ON di default; lo stato si ripristina al riavvio di HA.

    Quando è OFF l'auto non viene più svegliata automaticamente: i sensori restano
    sull'ultimo valore noto (aggiornabili a mano col pulsante "Aggiorna posizione")."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:autorenew"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Aggiornamento automatico", "polling_auto",
                         entity_id_format=ENTITY_ID_FORMAT)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # ripristina l'ultima scelta: se era OFF, ferma il poll avviato di default nel setup.
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.set_poll_enabled(last.state == "on")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.poll_enabled)

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_poll_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_poll_enabled(False)
        self.async_write_ha_state()


class Omoda9TheftAlarmSwitch(Omoda9OptimisticMixin, Omoda9Entity, SwitchEntity, RestoreEntity):
    """Antifurto dell'auto (theftAlarm setSwitch, endpoint /act).

    ON = l'auto fa scattare l'allarme e invia avvisi in caso di movimento non autorizzato,
    scasso porte, rottura finestrini o altre effrazioni (descrizione ufficiale dell'app).
    A differenza dei comfort, lo stato NON è in telemetria MQTT: si legge via REST
    (querySwitch). Strategia: seed iniziale dalla lettura reale, poi stato ottimistico dopo
    il toggle (il setSwitch ATTUA e vuole un tasko l'auto sveglia), e ripristino dell'ultimo
    stato noto al riavvio di HA."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:shield-car"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Antifurto", "antifurto", entity_id_format=ENTITY_ID_FORMAT)
        self._restored: bool | None = None
        self._real: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"
        # seed dello stato reale dal backend (read-only, best-effort: non deve rompere il setup)
        try:
            v = await self.coordinator.async_query_theft()
            if v is not None:
                self._real = v != 0
                self.async_write_ha_state()
        except Exception:  # noqa: BLE001
            pass

    @property
    def is_on(self) -> bool | None:
        if self._opt_value is not None:
            return self._opt_value
        if self._real is not None:
            return self._real
        return self._restored

    async def async_turn_on(self, **kwargs) -> None:
        await self._run_command("antifurto_on", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._run_command("antifurto_off", False)
