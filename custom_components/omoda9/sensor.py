"""Sensor: serratura (lock), livelli sedili (level) + batteria/velocità/sessione
+ sensori diagnostici del ponte (esiti comando/sveglia/sonda, timestamp).

Gli entity_id riproducono 1:1 quelli del bridge (omoda9_*) per continuità storico.
Tutti i sensori sono RestoreSensor: al riavvio di HA ripristinano l'ultimo valore
noto come fallback (parità col bridge, che persisteva via MQTT retained) finché non
arriva un dato live dall'auto.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FIELDS_AS_RICH_ENTITY
from .coordinator import SENSORS
from .entity import Omoda9Entity


# ───────────────────────── sensori "realtime" (Round B) ─────────────────────────
# Campi del canale REST /asr/manager/realtime (in coordinator.data["realtime"]),
# aggiornati al RISVEGLIO dell'auto (probe read-only). A differenza del 5A02 (MQTT),
# qui i VALORI reali di autonomia/odometro/gomme/consumi/ricarica ci sono davvero
# (sul 5A02 erano solo flag di unità "1"). Validati 1:1 contro il bean ufficiale
# CVRealtimeResBean dell'SDK Chery. Una tabella di spec evita 20+ classi gemelle.
#
# Valori/unità CONFERMATI dal vivo ad auto sveglia (2026-06-21, 84 campi):
#   pureElectricRange=60 km · mileageSurplus=215 km (totale) · cruiseRange=134 (stima)
#   lFrontTyreKpa=292 (=42 psi) → kPa · gomme temp 34-35 °C · *TyreCall/socLowCall=0=ok
#   oilSurplus=23 → LITRI (215−60=155 km a benzina /23 L ≈ 15 L/100km) · averageFuel=0.0
#   avgHkPowerKwh50km=20.6 → kWh/100km · totalVoltage=323.1 V · totalCurrent=0.0 A (HV reali!)
#   remainChargeTime ASSENTE ad auto non in carica (comparirà sotto carica).

C = UnitOfTemperature.CELSIUS
KM = UnitOfLength.KILOMETERS
KPA = UnitOfPressure.KPA
BAR = UnitOfPressure.BAR
MIN = UnitOfTime.MINUTES
VOLT = UnitOfElectricPotential.VOLT
AMP = UnitOfElectricCurrent.AMPERE
DIST = SensorDeviceClass.DISTANCE
TEMP = SensorDeviceClass.TEMPERATURE
PRESS = SensorDeviceClass.PRESSURE
DUR = SensorDeviceClass.DURATION
VOLTAGE = SensorDeviceClass.VOLTAGE
CURRENT = SensorDeviceClass.CURRENT
MEAS = SensorStateClass.MEASUREMENT
TOTAL = SensorStateClass.TOTAL_INCREASING


@dataclass(frozen=True)
class _RtSpec:
    """Spec di un sensore realtime. `numeric=False` → valore grezzo (stato/enum)."""

    suffix: str           # unique_id suffix (stabile): f"{vin}_rt_<suffix>"
    name: str             # nome → "Omoda9 <name>" → entity_id slugificato
    field: str            # chiave nel dict realtime
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    diag: bool = False
    numeric: bool = True
    vmap: dict | None = None  # codice grezzo → testo leggibile (campi enum)
    invalid: tuple = ()       # valori (float) = segnaposto "nessuna lettura" (HV spenta) → tieni l'ultimo noto
    compute: Callable | None = None  # valore CALCOLATO da più campi realtime (ignora `field`)
    scale: float | None = None  # fattore moltiplicativo sul valore grezzo (es. kPa→bar = 0.01)
    precision: int | None = None  # cifre decimali suggerite per la UI


# ── Mappe codice→testo per i campi enum di ricarica ──
# I valori sono enum a 3 stati ("0"/"1"/"2", confermati dai confronti nel codice
# dell'app `rus_car_state_model.dart`). `0` = stato a riposo verificato dal vivo
# (auto parcheggiata non in carica). La semantica di 1/2 segue la convenzione EV;
# qualunque codice non previsto resta leggibile come "Sconosciuto (N)" (vedi
# Omoda9RealtimeSensor._live_value) → nessuna informazione persa, nessun valore inventato.
CHARGE_STATE_MAP = {"0": "Non in ricarica", "1": "In ricarica", "2": "Ricarica completata"}
APPT_CHARGE_STATE_MAP = {"0": "Disattivata", "1": "Attiva", "2": "In esecuzione"}
FAST_GUN_MAP = {"0": "Scollegata", "1": "Collegata", "2": "Collegata (ricarica rapida)"}


def _range_totale(rt: dict):
    """Autonomia totale REALE = elettrica (`pureElectricRange`) + benzina (`mileageSurplus`).
    None se manca un pezzo → resta l'ultimo valore noto (RestoreSensor).

    ⚠️ NON usare `cruiseRange` come totale: il dump head unit lo dava per il combinato
    del cruscotto (ID_DISPLAY_MILEAGE), ma la cattura live SMENTISCE: `cruiseRange`=134
    è rimasto INVARIATO tra 2026-06-21 (elettrica=60) e 2026-06-25 (elettrica=116) mentre
    l'autonomia elettrica cambiava → è un valore statico/nominale, non il totale live.
    La somma elettrica+benzina segue lo stato batteria → è la scelta corretta."""
    try:
        return float(rt["pureElectricRange"]) + float(rt["mileageSurplus"])
    except (TypeError, ValueError, KeyError):
        return None


_RT_SENSORS: list[_RtSpec] = [
    # ── P1 · autonomia / chilometri (valori km confermati dal vivo) ──
    _RtSpec("range_elettrico", "Autonomia elettrica", "pureElectricRange",
            DIST, KM, MEAS, "mdi:map-marker-distance"),
    # mileageSurplus = autonomia a BENZINA (motore termico), NON il totale: verificato dal
    # vivo 2026-06-23 che resta 215 km mentre l'autonomia elettrica scende (60→27 km) e il
    # carburante è invariato (oilSurplus 23 L) → segue il serbatoio, non la batteria.
    _RtSpec("range_benzina", "Autonomia benzina", "mileageSurplus",
            DIST, KM, MEAS, "mdi:gas-station"),
    # Autonomia TOTALE = elettrica + benzina (campo CALCOLATO). Vedi _range_totale.
    # (cruiseRange NON usato come totale: smentito dalla cattura live, è statico — vedi sotto.)
    _RtSpec("range_totale", "Autonomia totale", "",
            DIST, KM, MEAS, "mdi:map-marker-distance", compute=_range_totale),
    # cruiseRange = valore "combinato" grezzo del cloud → diagnostico. ⚠️ Osservato STATICO
    # (134 km sia il 21/06 sia il 25/06 con elettrica 60→116) → semantica incerta, tenuto
    # solo come diagnostico, NON usato per l'autonomia totale.
    _RtSpec("range_combinato", "Autonomia combinata (stima)", "cruiseRange",
            DIST, KM, MEAS, "mdi:map-marker-distance", diag=True),
    _RtSpec("odometro", "Odometro", "odometer",
            DIST, KM, TOTAL, "mdi:counter"),
    _RtSpec("km_ibrido", "Chilometraggio ibrido", "hybridMileage",
            DIST, KM, TOTAL, "mdi:counter", diag=True),
    # ── P1 · TPMS pressione (campo auto in kPa → mostrata in BAR come nell'app: ÷100) ──
    _RtSpec("gomma_ant_sx_press", "Pressione gomma ant. SX", "lFrontTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_ant_dx_press", "Pressione gomma ant. DX", "rFrontTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_post_sx_press", "Pressione gomma post. SX", "lRearTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    _RtSpec("gomma_post_dx_press", "Pressione gomma post. DX", "rRearTyreKpa",
            PRESS, BAR, MEAS, "mdi:car-tire-alert", scale=0.01, precision=2),
    # ── P1 · TPMS temperatura (°C, diagnostica) ──
    _RtSpec("gomma_ant_sx_temp", "Temperatura gomma ant. SX", "lFrontTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_ant_dx_temp", "Temperatura gomma ant. DX", "rFrontTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_post_sx_temp", "Temperatura gomma post. SX", "lRearTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("gomma_post_dx_temp", "Temperatura gomma post. DX", "rRearTyreTemp",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    # ── P2 · consumi e residui (unità confermate dal vivo) ──
    _RtSpec("consumo_carburante", "Consumo medio carburante", "averageFuel",
            None, "L/100 km", MEAS, "mdi:gas-station"),
    # avgHkPowerKwh50km=20.6 dal vivo → kWh/100km (il nome "50km" è fuorviante).
    # -100 = segnaposto "nessun dato" ad auto ferma (HV spenta) → tieni l'ultimo noto.
    _RtSpec("consumo_elettrico", "Consumo medio elettrico", "avgHkPowerKwh50km",
            None, "kWh/100 km", MEAS, "mdi:lightning-bolt", invalid=(-100.0,)),
    # oilSurplus=23 dal vivo → LITRI (confermato dal calcolo autonomia benzina).
    _RtSpec("carburante_residuo", "Carburante residuo", "oilSurplus",
            None, "L", MEAS, "mdi:fuel"),
    # ── P2 · batteria alta tensione (valide SOLO ad auto in marcia/ricarica) ──
    # Da ferma l'auto manda 0 V / -1000 A = segnaposto "HV spenta", non letture reali:
    # marcati invalidi → il sensore tiene l'ultimo valore noto invece di azzerarsi.
    _RtSpec("tensione_hv", "Tensione batteria HV", "totalVoltage",
            VOLTAGE, VOLT, MEAS, "mdi:flash", diag=True, invalid=(0.0,)),
    _RtSpec("corrente_hv", "Corrente batteria HV", "totalCurrent",
            CURRENT, AMP, MEAS, "mdi:current-dc", diag=True, invalid=(-1000.0,)),
    # ── P2 · ricarica ──
    # remainChargeTime: ASSENTE ad auto non in carica (comparirà sotto carica). Assunto
    # in MINUTI — da riconfermare a vettura in carica. chargeState/appointmentChargeState/
    # fastChargingGunStatus = codici (tutti 0 = a riposo dal vivo) → grezzi da decodificare.
    _RtSpec("tempo_ricarica", "Tempo di ricarica residuo", "remainChargeTime",
            DUR, MIN, None, "mdi:timer-sand"),
    _RtSpec("stato_ricarica", "Stato ricarica", "chargeState",
            None, None, None, "mdi:ev-station", diag=True, numeric=False,
            vmap=CHARGE_STATE_MAP),
    _RtSpec("ricarica_prog_stato", "Ricarica programmata · stato", "appointmentChargeState",
            None, None, None, "mdi:calendar-clock", diag=True, numeric=False,
            vmap=APPT_CHARGE_STATE_MAP),
    _RtSpec("presa_rapida", "Presa ricarica rapida", "fastChargingGunStatus",
            None, None, None, "mdi:ev-plug-ccs2", diag=True, numeric=False,
            vmap=FAST_GUN_MAP),
    # ── P2 · clima target ──
    _RtSpec("temp_imp_sx", "Temperatura impostata SX", "frontSetTempLeft",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    _RtSpec("temp_imp_dx", "Temperatura impostata DX", "frontSetTempRight",
            TEMP, C, MEAS, "mdi:thermometer", diag=True),
    # NB (2026-06-25): la cattura live del payload realtime (91 campi) ha SMENTITO i campi
    # del bean SDK che NON sono inviati da questa vettura (inCarTemperature, a/bOdoMeter,
    # chargingPower, averageSpeed, insFuelConsum, fastRemainChargeTime, tmpParkCountdown):
    # rimossi perché restavano `unknown` per sempre. Le novità verificate (oilCall/
    # electricityCall/engineState/hVoltageState) sono binary_sensor → vedi binary_sensor.py.
]


def _rt(coord, field: str) -> str | None:
    """Valore grezzo del campo realtime, o None se assente/vuoto."""
    rt = coord.data.get("realtime") or {}
    v = rt.get(field)
    if v is None or str(v).strip() in ("", "None"):
        return None
    return str(v)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    ents: list = [
        Omoda9FieldSensor(coord, s)
        for s in SENSORS
        if s["comp"] == "sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY
    ]
    ents.append(Omoda9Battery(coord))
    ents.append(Omoda9Speed(coord))
    # — sensori "ricchi" dal canale realtime (Round B): autonomia, odometro, gomme,
    #   consumi, ricarica, clima target —
    ents += [Omoda9RealtimeSensor(coord, s) for s in _RT_SENSORS]
    ents.append(Omoda9SessionStatus(coord))
    # — sensori diagnostici (parità col bridge) —
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito comando", "cmd_status", "cmd_status", "mdi:car-cog"))
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito sveglia", "wake_status", "wake_status", "mdi:car-connected"))
    ents.append(Omoda9TextSensor(coord, "Omoda9 Esito sonda posizione", "probe_status", "probe_status", "mdi:crosshairs-gps"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultimo contatto", "lastseen", "last_seen", "mdi:car-clock"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultima sveglia", "wake_ts", "last_wake", "mdi:car-clock"))
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Ultima posizione", "pos_fix", "last_pos_fix", "mdi:map-marker-clock"))
    # [2.0] freschezza del frame auto (resultTime del realtime): quanto è vecchio il dato
    #       batteria/odometro mostrato — utile ad auto ferma per sapere se è recente o stantio.
    ents.append(Omoda9TimestampSensor(coord, "Omoda9 Dati auto aggiornati", "car_data_ts", "car_data_ts", "mdi:database-clock"))
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
    """serratura (0=Bloccata/1=Sbloccata), livello sedile (Livello N) o valore grezzo."""

    def __init__(self, coord, spec: dict) -> None:
        super().__init__(coord, f"Omoda9 {spec['name']}", spec["key"])
        self._key = spec["key"]
        self._kind = spec["kind"]
        if spec.get("icon"):
            self._attr_icon = spec["icon"]
        # campi tecnici (es. codice di fase del tetto) → tra i dettagli diagnostici
        if spec.get("diag"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

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
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Batteria", "battery")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        if "dumpEnergy" not in rt:
            return None
        try:
            soc = float(rt["dumpEnergy"])
        except (TypeError, ValueError):
            return None
        # dumpEnergy=0 = segnaposto "alta tensione spenta" (auto ferma), NON una carica
        # reale dello 0%: torna None così resta l'ultimo SOC noto (come fa l'app ufficiale).
        if soc <= 0:
            return None
        return soc

    @property
    def native_value(self):
        live = self._live_value()
        if live is not None:
            return live
        # non riproporre uno "0%" stantio salvato prima del fix dei segnaposto: 0 non è un
        # ultimo-valore-noto valido per la batteria → meglio "sconosciuto" finché non arriva
        # una lettura vera (primo viaggio/ricarica o pulsante "Aggiorna stato completo").
        if self._restored in (0, 0.0, "0", "0.0"):
            return None
        return self._restored


class Omoda9Speed(_Omoda9RestoreSensor):
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:speedometer"

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Velocità", "speed")

    def _live_value(self):
        rt = self.coordinator.data.get("realtime") or {}
        try:
            return float(rt["vehicleSpeed"]) if "vehicleSpeed" in rt else None
        except (TypeError, ValueError):
            return None


class Omoda9RealtimeSensor(_Omoda9RestoreSensor):
    """Sensore generico su un campo del canale realtime (vedi `_RT_SENSORS`).

    Stesso pattern di `Omoda9Battery`/`Omoda9Speed` ma parametrico: device_class,
    unità e state_class arrivano dalla spec. `numeric=True` converte a float (None
    se non parsabile → emerge l'ultimo valore noto del RestoreSensor); `numeric=False`
    tiene il valore grezzo (codici di stato ricarica da decodificare)."""

    def __init__(self, coord, spec: _RtSpec) -> None:
        super().__init__(coord, f"Omoda9 {spec.name}", f"rt_{spec.suffix}")
        self._spec = spec
        if spec.device_class:
            self._attr_device_class = spec.device_class
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit
        if spec.state_class:
            self._attr_state_class = spec.state_class
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.precision is not None:
            self._attr_suggested_display_precision = spec.precision
        if spec.diag:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _live_value(self):
        # campo CALCOLATO da più field realtime (es. autonomia totale = elettrica + benzina)
        if self._spec.compute is not None:
            rt = self.coordinator.data.get("realtime") or {}
            val = self._spec.compute(rt)
            return None if (val is None or val in self._spec.invalid) else val
        raw = _rt(self.coordinator, self._spec.field)
        if raw is None:
            return None
        if self._spec.vmap is not None:
            key = raw[:-2] if raw.endswith(".0") else raw  # "0.0" → "0"
            return self._spec.vmap.get(key, f"Sconosciuto ({raw})")
        if not self._spec.numeric:
            return raw
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        # segnaposto "nessuna lettura" (es. HV spenta) → None ⇒ resta l'ultimo valore noto
        if val in self._spec.invalid:
            return None
        return val * self._spec.scale if self._spec.scale is not None else val


class Omoda9SessionStatus(_Omoda9RestoreSensor):
    _attr_icon = "mdi:key-chain"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        super().__init__(coord, "Omoda9 Stato sessione", "session_detail")

    def _live_value(self):
        return self.coordinator.data.get("session_detail") or None


class Omoda9TextSensor(_Omoda9RestoreSensor):
    """Sensore testuale diagnostico (esito ultimo comando/sveglia/sonda)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str) -> None:
        super().__init__(coord, name, suffix)
        self._data_key = data_key
        self._attr_icon = icon

    def _live_value(self):
        return self.coordinator.data.get(self._data_key) or None

    @property
    def native_value(self):
        # [H9] gli esiti diagnostici (comando/sveglia/sonda) NON si ripristinano: un
        # esito vecchio dopo un restart sarebbe fuorviante (sembrerebbe l'ultima azione
        # appena eseguita). Solo il valore live; in assenza → unknown.
        return self._live_value()


class Omoda9TimestampSensor(_Omoda9RestoreSensor):
    """Timestamp diagnostico (ultimo contatto/sveglia/posizione)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, name: str, suffix: str, data_key: str, icon: str) -> None:
        super().__init__(coord, name, suffix)
        self._data_key = data_key
        self._attr_icon = icon

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # [H10] device_class TIMESTAMP esige un datetime tz-aware: valida il valore
        # ripristinato (stringa ISO → parse), altrimenti None, per non emettere il
        # warning HA "Invalid datetime" e non mostrare un timestamp malformato.
        r = self._restored
        if isinstance(r, str):
            r = dt_util.parse_datetime(r)
        if not (isinstance(r, datetime) and r.tzinfo is not None):
            r = None
        self._restored = r

    def _live_value(self):
        return self.coordinator.data.get(self._data_key)
