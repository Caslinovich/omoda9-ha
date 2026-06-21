"""Coordinator Omoda 9 — sostituisce ha_bridge.py (MQTT auto + sonda) in modo nativo.

Riceve via MQTT (mutual-TLS, paho in un thread) gli eventi 5A02 dell'auto, ne fa il
parsing (stesso identico mapping del bridge: vedi SENSORS) e tiene lo stato corrente
in `self.data`. Le entità native leggono da qui. Comandi/sveglia/sonda/sessione sono
delegati al "cuore di protocollo" in `core/` (eseguito in executor).

NB: i moduli `core/` leggono la config da env a import-time → impostiamo os.environ
DALL'entry prima di importarli (assunzione: una sola auto per istanza HA).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import ssl
import threading
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CAR_SEED, DEFAULT_AWAKE_WINDOW, DEFAULT_SESSION_EVERY, CERT_FILES,
    CONF_VIN, CONF_TUSERID, CONF_PIN, CONF_EMAIL, CONF_CERTS_SRC,
    CONF_BFF, CONF_TSP_HOST, CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, CONF_CHANNEL_ID,
    CONF_POLL_NORMAL, CONF_POLL_CHARGING, DEFAULT_POLL_NORMAL_MIN,
    DEFAULT_POLL_CHARGING_MIN, POLL_WAKE_WAIT, COMMAND_LOCK_S,
    DEFAULTS,
)

# Cert minimi per il mutual-TLS MQTT (il .cer del server non serve a tls_set, come nel bridge).
REQUIRED_CERTS = ("ca.pem", "client.pem", "client.key")

_LOGGER = logging.getLogger(__name__)

# Mappa campo-auto → entità (identica al bridge: ha_bridge.py SENSORS).
# kind: open|onoff → binary_sensor ON se != 0 ; lock → 0=Bloccata/1=Sbloccata ; level → sensor 0-3
SENSORS = [
    {"key": "frontLeftDoor",  "name": "Porta anteriore SX",  "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "frontRightDoor", "name": "Porta anteriore DX",  "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "backLeftDoor",   "name": "Porta posteriore SX", "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "backRightDoor",  "name": "Porta posteriore DX", "comp": "binary_sensor", "dclass": "door",   "kind": "open"},
    {"key": "trunkDoor",      "name": "Baule",               "comp": "binary_sensor", "dclass": "opening","kind": "open"},
    {"key": "hood",           "name": "Cofano",              "comp": "binary_sensor", "dclass": "opening","kind": "open"},
    {"key": "liftgateOperateState", "name": "Portellone in movimento", "comp": "binary_sensor", "dclass": "moving", "kind": "onoff"},
    {"key": "doorLock",       "name": "Serratura",           "comp": "sensor",        "dclass": None,     "kind": "lock"},
    {"key": "frontLeftWindowState",  "name": "Finestrino anteriore SX",  "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "frontRightWindowState", "name": "Finestrino anteriore DX",  "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "backLeftWindowState",   "name": "Finestrino posteriore SX", "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "backRightWindowState",  "name": "Finestrino posteriore DX", "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "sunroofState",   "name": "Tetto apribile",      "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "sunshadeState",  "name": "Tendina tetto",       "comp": "binary_sensor", "dclass": "window", "kind": "open", "diag": True},
    {"key": "frontHVACState", "name": "Clima",               "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "airPurification","name": "Purificazione aria",  "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "frontWindshieldHeat", "name": "Sbrinamento parabrezza", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "fWinHeatingState","name": "Riscaldamento parabrezza", "comp": "binary_sensor", "dclass": "running", "kind": "onoff", "diag": True},
    {"key": "rWinHeatingState","name": "Riscaldamento lunotto",    "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "steerWheelHeating","name": "Riscaldamento volante",   "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "dSeatHeatingState","name": "Riscaldamento sedile guida",     "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "pSeatHeatingState","name": "Riscaldamento sedile passeggero","comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "dSeatVentilateState","name": "Ventilazione sedile guida",      "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "pSeatVentilateState","name": "Ventilazione sedile passeggero", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "lSeatHeatingState2","name": "Riscaldamento sedile post. SX",      "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "rSeatHeatingState2","name": "Riscaldamento sedile post. DX",      "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "mSeatHeatingState2","name": "Riscaldamento sedile post. centrale","comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-heater"},
    {"key": "lSeatVentilateState2","name": "Ventilazione sedile post. SX",       "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    {"key": "rSeatVentilateState2","name": "Ventilazione sedile post. DX",       "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    {"key": "mSeatVentilateState2","name": "Ventilazione sedile post. centrale", "comp": "sensor", "dclass": None, "kind": "level", "icon": "mdi:car-seat-cooler"},
    # — telemetria aggiuntiva (campi già inviati dall'auto nel 5A02) —
    {"key": "chargeGunState", "name": "Spina ricarica",  "comp": "binary_sensor", "dclass": "plug",    "kind": "onoff"},
    {"key": "engineState",    "name": "Motore",          "comp": "binary_sensor", "dclass": "running", "kind": "onoff", "icon": "mdi:engine"},
    # sunroofMoveState = codice di FASE di movimento del tetto (valori 1/2/3/4/8, mai 0):
    # non è un on/off pulito (non c'è un valore "fermo" noto) → sensore diagnostico raw.
    {"key": "sunroofMoveState", "name": "Tetto · stato movimento", "comp": "sensor", "dclass": None, "kind": "value", "icon": "mdi:car-select", "diag": True},
    # NB campi NON mappati di proposito (verificato su events.jsonl reali, 2026-06-21):
    #   rangeUnit / averageFuelUnit / tirePressureUnit valgono SEMPRE "1" = sono FLAG di
    #   unità di misura, NON il valore. L'auto non invia su questo canale il valore reale
    #   di autonomia/consumo/pressione gomme → mapparli mostrerebbe "1" fisso. Rimandati:
    #   serve l'altro canale (realtime /asr/manager o struttura TPMS annidata) → Round B.
]
META = {s["key"]: s for s in SENSORS}

# Meta-campi dei push di CONFERMA comando (110x/1105/1135…): NON sono telemetria di
# stato del veicolo → non vanno messi tra i "fields" (vedi _on_car_message / Item 4).
CMD_CONFIRM_META = ("result", "resultTime", "seq", "reason", "hasAsy")

# [MED] Campi "geo" ammessi in self.position (push 1301 / sonda realtime). Si tiene
# SOLO la geolocalizzazione: batteria/velocità/online vivono in self.data["realtime"].
GEO_KEYS = ("lat", "lon", "latitude", "longitude", "speed", "vehicleSpeed",
            "direction", "heading", "altitude", "gpsTime", "positionTime")


class Omoda9Coordinator(DataUpdateCoordinator):
    """Tiene la connessione MQTT all'auto e lo stato; espone azioni via core/."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        cfg = {**DEFAULTS, **dict(entry.data)}
        self.vin = cfg[CONF_VIN]
        self.tuserid = cfg[CONF_TUSERID]
        self.channel_id = str(cfg.get(CONF_CHANNEL_ID, "1"))
        self.car_host = cfg[CONF_CAR_MQTT_HOST]
        self.car_port = int(cfg[CONF_CAR_MQTT_PORT])
        self.awake_window = DEFAULT_AWAKE_WINDOW
        # per-entry storage (token + certs) nella config dir di HA
        self.token_path = hass.config.path(f"{DOMAIN}_{self.vin}_token.json")
        self.certs_dir = hass.config.path(f"{DOMAIN}_{self.vin}_certs")
        self.certs_src = cfg.get(CONF_CERTS_SRC) or ""
        self.tsp_host = cfg[CONF_TSP_HOST]
        self.pin = cfg.get(CONF_PIN, "")
        self.bff = cfg[CONF_BFF]
        self.email = cfg.get(CONF_EMAIL, "")

        # env per i moduli core/ (li importeremo DOPO aver settato l'ambiente).
        # [H1] Assegnazione DIRETTA (non setdefault): con più entry/reload nello stesso
        # processo, setdefault terrebbe i valori del PRIMO entry → config stale.
        os.environ["VIN"] = self.vin
        os.environ["TUSERID"] = self.tuserid
        os.environ["CHANNEL_ID"] = self.channel_id
        os.environ["OMODA_TOKEN_PATH"] = self.token_path
        os.environ["OMODA_BFF"] = self.bff
        os.environ["TSP_HOST"] = self.tsp_host
        if self.pin:
            os.environ["OMODA_PIN"] = self.pin
        if self.email:
            os.environ["OMODA_EMAIL"] = self.email

        self._car = None  # paho mqtt.Client (importato in _connect_car, executor)
        self._keepalive_unsub = None  # cancella il timer keep-alive sessione
        # poll telemetria periodico (sveglia+lettura). Intervalli in MINUTI dalle opzioni
        # (0 = off): a riposo `poll_normal_min`, alla colonnina `poll_charging_min`.
        opt = entry.options or {}
        self.poll_normal_min = int(opt.get(CONF_POLL_NORMAL, DEFAULT_POLL_NORMAL_MIN))
        self.poll_charging_min = int(opt.get(CONF_POLL_CHARGING, DEFAULT_POLL_CHARGING_MIN))
        self._poll_unsub = None       # cancella il timer del poll (async_call_later)
        self._poll_busy = False       # evita sovrapposizioni tra cicli
        # interruttore "Aggiornamento automatico" (switch): SPENTO di default — il poll
        # sveglia l'auto, quindi parte solo se l'utente lo accende esplicitamente. La
        # scelta dell'utente viene poi ricordata tra i riavvii (switch RestoreEntity).
        self.poll_enabled = False
        self._cmd_busy_until = 0.0     # anti-doppio-tap: monotonic fino a cui un comando è "in volo"
        self._fields: dict[str, str] = {}
        self._state_lock = threading.Lock()  # [H2] serializza _fields/position tra thread paho/executor/loop
        self._last_msg_ts: float = 0.0
        self.position: dict | None = None
        self.otp_code: str = ""   # impostato dall'entità text «Codice OTP», letto da confirm
        self.data = {"fields": {}, "position": None,
                     "awake": False, "car_connected": False,
                     "session_ok": None, "session_detail": "",
                     # — sensori diagnostici (parità col bridge) —
                     "cmd_status": None, "wake_status": None, "probe_status": None,
                     "last_seen": None, "last_wake": None, "last_pos_fix": None,
                     "realtime": None}

    # ───────────────── provisioning certificati mutual-TLS (FASE 3c) ─────────────────
    async def async_provision_certs(self) -> tuple[bool, str]:
        """Garantisce i cert mutual-TLS nella certs_dir per-entry. Ritorna (ok, dettaglio).

        Strategia (il provisioning ex-novo dei cert non è ancora automatizzabile —
        i 4 cert nascono dalla registrazione device dell'app, non riproducibile qui):
          1) se i 3 cert richiesti sono GIÀ nella certs_dir → ok;
          2) altrimenti, se `certs_src` (cartella dentro il filesystem di HA) li
             contiene → li copia nella certs_dir;
          3) altrimenti → (False) con istruzioni su dove metterli a mano.
        """
        return await self.hass.async_add_executor_job(self._provision_certs)

    def _provision_certs(self) -> tuple[bool, str]:
        os.makedirs(self.certs_dir, mode=0o700, exist_ok=True)

        def _have_required() -> bool:
            return all(os.path.isfile(os.path.join(self.certs_dir, f)) for f in REQUIRED_CERTS)

        if _have_required():
            return True, "cert presenti"

        # 1) override manuale: cartella indicata in certs_src
        if self.certs_src and os.path.isdir(self.certs_src):
            copied = []
            for f in CERT_FILES:
                src = os.path.join(self.certs_src, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(self.certs_dir, f))
                    os.chmod(os.path.join(self.certs_dir, f), 0o600)
                    copied.append(f)
            if _have_required():
                return True, f"cert importati da {self.certs_src}: {', '.join(copied)}"

        # 2) auto-provisioning dai cert universali per-regione bundlati (vedi cert_bundle)
        try:
            from .cert_bundle import decrypt_region
            certs = decrypt_region(self.car_host)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[certs] bundle non disponibile per %s: %s", self.car_host, err)
            certs = None
        if certs:
            try:
                for name, data in certs.items():
                    p = os.path.join(self.certs_dir, name)
                    with open(p, "wb") as fh:
                        fh.write(data)
                    os.chmod(p, 0o600)
            except OSError as err:
                return False, f"scrittura cert dal bundle fallita in {self.certs_dir}: {err}"
            if _have_required():
                return True, f"cert auto-provisioned ({self.car_host})"

        return False, (f"cert mutual-TLS mancanti per {self.car_host}: regione non nel bundle. "
                       f"Copia {', '.join(REQUIRED_CERTS)} in {self.certs_dir} "
                       f"(oppure indica una cartella in certs_src).")

    # ───────────────── ciclo di vita MQTT auto ─────────────────
    async def async_start(self) -> None:
        """Avvia la connessione MQTT all'auto (paho gira in un thread proprio)."""
        await self.hass.async_add_executor_job(self._connect_car)

    # ───────────────── keep-alive sessione (refresh token periodico) ─────────────────
    def async_start_keepalive(self) -> None:
        """Pianifica un refresh sessione periodico per non far scadere il token.

        `_bff_login` rinnova da sé l'access_token col refresh_token quando scade
        (senza OTP) → ricontrollare la sessione ogni `DEFAULT_SESSION_EVERY` tiene
        viva la sessione anche da fermi (rotazione del refresh_token prima che la
        sua finestra si chiuda) ed evita un re-OTP a sorpresa per inattività. Come
        bonus aggiorna le entità sessione. Non protegge dall'apertura dell'app
        ufficiale (sessione singola lato cloud → serve comunque OTP)."""
        if self._keepalive_unsub is not None:
            return
        self._keepalive_unsub = async_track_time_interval(
            self.hass, self._keepalive, timedelta(seconds=DEFAULT_SESSION_EVERY)
        )

    async def _keepalive(self, _now) -> None:
        try:
            ok, detail = await self.async_check_session()
            _LOGGER.debug("[keepalive] sessione %s — %s", "ok" if ok else "KO", detail)
        except Exception as err:  # noqa: BLE001 — un errore di rete non deve fermare il timer
            _LOGGER.debug("[keepalive] errore non bloccante: %s", err)

    # ───────────────── poll telemetria periodico (sveglia + lettura) ─────────────────
    def async_start_telemetry_poll(self) -> None:
        """Avvia il poll periodico se almeno un intervallo è attivo (>0).

        Timer auto-rischedulante (`async_call_later`): l'intervallo è DINAMICO — più
        breve quando l'auto è attaccata alla colonnina (`poll_charging_min`), altrimenti
        `poll_normal_min`. Ogni ciclo SVEGLIA l'auto (vehicleLocation = posizione) e
        forza una lettura realtime (telemetria)."""
        if not self.poll_enabled:
            _LOGGER.debug("[poll] disattivato dall'interruttore")
            return
        if self.poll_normal_min <= 0 and self.poll_charging_min <= 0:
            _LOGGER.debug("[poll] disattivato (entrambi gli intervalli a 0)")
            return
        if self._poll_unsub is None:
            self._schedule_next_poll()

    @callback
    def set_poll_enabled(self, on: bool) -> None:
        """Attiva/disattiva il poll periodico a runtime (switch "Aggiornamento automatico")."""
        self.poll_enabled = on
        if on:
            self.async_start_telemetry_poll()
        elif self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None

    def _is_plugged(self) -> bool:
        """True se la spina di ricarica è collegata (chargeGunState != 0). Legge il
        valore più fresco: realtime se presente, altrimenti l'ultimo 5A02 via MQTT."""
        from .entity import field_on
        rt = self.data.get("realtime") or {}
        v = rt.get("chargeGunState")
        if v is None:
            with self._state_lock:
                v = self._fields.get("chargeGunState")
        return bool(field_on(v))

    def _schedule_next_poll(self) -> None:
        """Rischedula il prossimo poll in base allo stato spina attuale. Se lo stato
        corrente ha intervallo 0 (modalità disattivata) NON sveglia, ma ricontrolla più
        tardi (per accorgersi quando cambia l'attacco alla colonnina)."""
        mins = self.poll_charging_min if self._is_plugged() else self.poll_normal_min
        if not mins or mins <= 0:
            # stato attuale off → recheck con l'altro intervallo (o 60 min) senza svegliare
            mins = self.poll_charging_min or self.poll_normal_min or 60
        self._poll_unsub = async_call_later(self.hass, mins * 60, self._telemetry_poll_cb)

    async def _telemetry_poll_cb(self, _now) -> None:
        self._poll_unsub = None
        try:
            mins = self.poll_charging_min if self._is_plugged() else self.poll_normal_min
            if mins and mins > 0 and not self._poll_busy:
                self._poll_busy = True
                try:
                    await self._do_poll_cycle()
                finally:
                    self._poll_busy = False
        except Exception as err:  # noqa: BLE001 — un errore non deve fermare il timer
            _LOGGER.debug("[poll] errore non bloccante: %s", err)
        finally:
            self._schedule_next_poll()

    async def _do_poll_cycle(self) -> None:
        """Un ciclo: sveglia (posizione via vehicleLocation/1301) + lettura realtime."""
        _LOGGER.debug("[poll] ciclo: sveglia + lettura realtime (plugged=%s)", self._is_plugged())
        try:
            await self.async_send_command("localizza")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[poll] sveglia (localizza) fallita: %s", err)
        await asyncio.sleep(POLL_WAKE_WAIT)
        try:
            await self.async_probe(force=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[poll] lettura realtime fallita: %s", err)

    def _connect_car(self) -> None:
        self._bind_core()
        # import qui (executor): a livello modulo causa un blocking-call warning nel loop.
        import paho.mqtt.client as mqtt

        seed = os.environ.get("CAR_SEED", CAR_SEED)
        car_user = self.tuserid
        car_pass = hashlib.md5((self.tuserid + seed).encode()).hexdigest()
        client_id = f"app_{self.channel_id}_{self.tuserid}"   # esatto: ACL del broker
        topic = f"app/{self.channel_id}/{self.tuserid}/account/msgCenter/msg"

        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=client_id, protocol=mqtt.MQTTv311, clean_session=False)
        c.username_pw_set(car_user, car_pass)
        c.tls_set(ca_certs=os.path.join(self.certs_dir, "ca.pem"),
                  certfile=os.path.join(self.certs_dir, "client.pem"),
                  keyfile=os.path.join(self.certs_dir, "client.key"),
                  cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        c.tls_insecure_set(True)  # il broker usa un CN non combaciante (come nel bridge)

        def on_connect(cl, u, flags, rc, props=None):
            ok = (rc == 0) or (getattr(rc, "value", 1) == 0)
            self._update({"car_connected": ok})
            _LOGGER.info("[auto] MQTT on_connect rc=%s → %s (sub %s)",
                         rc, "connesso" if ok else "RIFIUTATO", topic if ok else "-")
            if ok:
                cl.subscribe(topic, qos=1)

        def on_disconnect(cl, u, *a):
            self._update({"car_connected": False})
            _LOGGER.info("[auto] MQTT disconnesso")

        c.on_connect = on_connect
        c.on_disconnect = on_disconnect
        c.on_message = self._on_car_message
        # [H4] backoff di riconnessione (evita lo storming a 1s di default su rete giù)
        c.reconnect_delay_set(min_delay=1, max_delay=120)
        # [H4] il connect iniziale può fallire (DNS/cert/rete) → ConfigEntryNotReady,
        #      così HA riprova il setup invece di lasciare il client appeso.
        try:
            c.connect(self.car_host, self.car_port, keepalive=60)
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(
                f"connessione MQTT auto fallita ({self.car_host}:{self.car_port}): {err}"
            ) from err
        c.loop_start()
        self._car = c

    def async_stop(self) -> None:
        """[MED] Spegnimento MQTT. Bloccante (loop_stop fa join del thread paho) →
        chiamato in executor da async_unload_entry. `disconnect()` PRIMA di
        `loop_stop()`: così il loop processa il CONNACK/DISCONNECT e il thread esce
        pulito senza un join che attende il keepalive."""
        if self._keepalive_unsub is not None:
            self._keepalive_unsub()
            self._keepalive_unsub = None
        if self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None
        if self._car is not None:
            try:
                self._car.disconnect()
                self._car.loop_stop()
            except Exception as err:  # noqa: BLE001 — lo stop non deve far fallire l'unload
                _LOGGER.debug("[auto] errore in async_stop: %s", err)
            self._car = None

    def _on_car_message(self, c, u, msg) -> None:
        """Parsing identico a ha_bridge.car_on_message (thread paho → push verso HA)."""
        try:
            obj = json.loads(msg.payload.decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[auto] payload MQTT non decodificabile: %s", err)
            return
        content = obj.get("content", obj)
        data = content.get("data", {}) if isinstance(content, dict) else {}
        if not isinstance(data, dict):
            data = {}
        svc = str(content.get("serviceType")) if isinstance(content, dict) else ""
        now = time.time()
        now_dt = dt_util.utcnow()
        _LOGGER.debug("[auto] messaggio ricevuto (svc %s): %d campi", svc or "?", len(data))

        patch = {"last_seen": now_dt}

        # [MED] serviceType 1301 = push POSIZIONE (lat/lon) → device_tracker. Si
        # discrimina sul TIPO messaggio (non sulla sola presenza di lat/lon) e si
        # tiene in position SOLO la geolocalizzazione (no **data).
        if svc == "1301" and "lat" in data and "lon" in data:
            geo = {k: data[k] for k in GEO_KEYS if k in data}
            with self._state_lock:
                self.position = geo
                pos_copy = dict(geo)
            patch["position"] = pos_copy
            patch["last_pos_fix"] = now_dt

        # [Item4] push di CONFERMA comando: l'auto risponde a ogni vehicleControl/X con un
        # messaggio 110x/1105/1135 che porta result/resultTime/seq (+ reason sui guasti)
        # OLTRE ai campi di stato reali. Lo riconosciamo dalla presenza di result/seq (la
        # telemetria 5A02 "pura" non li ha). I campi di stato vanno comunque in fields;
        # i meta-campi (CMD_CONFIRM_META) NO (non sono stato del veicolo).
        is_confirmation = "result" in data or "seq" in data

        # [H2] _fields/_last_msg_ts toccati anche dall'executor → sotto lock; emetti una COPIA
        with self._state_lock:
            was_awake = bool(self._last_msg_ts) and (now - self._last_msg_ts) < self.awake_window
            self._last_msg_ts = now
            for k, v in data.items():
                if k != "time" and k not in CMD_CONFIRM_META:
                    self._fields[k] = str(v)
            fields_copy = dict(self._fields)

        patch.update({"fields": fields_copy, "awake": True})
        if is_confirmation:
            patch["cmd_status"] = self._format_cmd_result(data)
            self.clear_command_busy()  # comando risolto → sblocca subito il prossimo (anti-doppio-tap)
        self._update(patch)

        # [H3] fronte di risveglio → una sonda realtime (sola lettura). Lo schedule del
        # task DEVE avvenire sul loop: dal thread paho usa call_soon_threadsafe.
        if not was_awake:
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self.async_probe())
            )

    @staticmethod
    def _format_cmd_result(data: dict) -> str:
        """Traduce l'esito REALE di un push di conferma comando in una frase per l'utente.

        Distinto dall'"accettato" del backend (A00079, mostrato all'invio): qui è ciò che
        l'AUTO riporta dopo aver provato a eseguire. Interpretazione CONSERVATIVA, basata
        sui dati reali (events.jsonl 2026-06-21) e sul significato del bean:
          - `reason` (lista) è popolato SOLO sui guasti → se presente = NON riuscito;
          - `result`: 5 = operazione asincrona ancora in corso (sempre con hasAsy=1);
            1/2 = eseguito/applicato (stato del veicolo aggiornato);
          - codici diversi → riportati grezzi, senza inventarne il significato."""
        result = str(data.get("result", "")).strip()
        reason = data.get("reason")
        if reason:  # lista di motivi di fallimento segnalati dall'auto
            return f"L'auto ha segnalato un problema ❌ ({reason})"[:255]
        if result == "5":
            return "Comando in esecuzione sull'auto… ⏳"
        if result in ("1", "2"):
            return "Comando eseguito e confermato dall'auto ✅"
        return f"Conferma ricevuta dall'auto (codice esito {result or '?'})"[:255]

    def _update(self, patch: dict) -> None:
        """Aggiorna self.data e notifica le entità (thread-safe dal thread paho)."""
        self.hass.loop.call_soon_threadsafe(self._apply_update, patch)

    def _apply_update(self, patch: dict) -> None:
        self.data = {**self.data, **patch}
        self.async_set_updated_data(self.data)

    # ───────────────── bind config → moduli core/ ─────────────────
    def _bind_core(self) -> None:
        """Inietta la config di QUESTO entry nei global dei moduli core/.

        I moduli core/ leggono VIN/PIN/token-path/TSP da env A IMPORT-TIME: se il
        config flow li ha già importati (con VIN ignoto), o se un ALTRO entry ha
        importato per primo, i loro global resterebbero stale nello stesso processo.
        [H1] Qui li forziamo TUTTI ai valori di QUESTO entry → robusto rispetto
        all'ordine di import e a entry/reload multipli. Idempotente, in executor."""
        import wake, commands, probe, session
        import omoda_auth as A
        # env per i moduli che lo rileggono a runtime (wake._token_path, omoda.py, …)
        os.environ["OMODA_TOKEN_PATH"] = self.token_path
        os.environ["VIN"] = self.vin
        os.environ["TUSERID"] = self.tuserid
        os.environ["CHANNEL_ID"] = self.channel_id
        # global per-account dei moduli core/
        wake.VIN = self.vin
        wake.TSP_HOST = self.tsp_host
        wake.TOKEN_PATH = self.token_path
        commands.VIN = self.vin
        commands.PIN = self.pin
        commands.TSP_HOST = self.tsp_host
        # MINT_TASKID dal valore d'ambiente (default 1 = i pulsanti coniano il proprio
        # taskId, fix S26) — rivalutato qui per non restare stale tra entry/reload.
        commands.MINT_TASKID = os.environ.get("OMODA_MINT_TASKID", "1") not in ("0", "", "false", "no")
        # taskId file nella config dir per-VIN (sopravvive agli update HACS, niente stale condiviso)
        commands.TASKID_FILE = self.hass.config.path(f"{DOMAIN}_{self.vin}_taskid.txt")
        probe.VIN = self.vin
        session.EMAIL = self.email
        A.BFF = self.bff
        A.CHANNEL_ID = self.channel_id
        A.COUNTRY_ID = os.environ.get("OMODA_COUNTRY_ID", A.COUNTRY_ID)

    # ───────────────── anti-doppio-tap (un comando alla volta) ─────────────────
    @callback
    def command_busy(self) -> bool:
        """True se un comando attuativo è ancora "in volo" (inviato da poco, conferma
        non ancora arrivata). L'auto ne esegue uno alla volta → blocca i doppi-tap."""
        return time.monotonic() < self._cmd_busy_until

    @callback
    def mark_command_sent(self) -> None:
        self._cmd_busy_until = time.monotonic() + COMMAND_LOCK_S

    @callback
    def clear_command_busy(self) -> None:
        self._cmd_busy_until = 0.0

    # ───────────────── azioni (delega a core/, in executor) ─────────────────
    async def async_send_command(self, key: str, params: dict | None = None) -> str:
        return await self.hass.async_add_executor_job(self._send_command, key, params)

    def _send_command(self, key: str, params: dict | None = None) -> str:
        self._bind_core()
        self.mark_command_sent()  # copre anche poll/wake (localizza) che non passano dal mixin
        import commands as CMD  # core/ è sul path (vedi __init__)
        msgs: list[str] = []

        def emit(m):
            msgs.append(str(m))
            _LOGGER.info("[cmd] %s", m)
            self._update({"cmd_status": str(m)[:255]})

        CMD.send(key, emit=emit, params=params)
        return msgs[-1] if msgs else "inviato"

    async def async_query_theft(self) -> int | None:
        """Stato antifurto via REST (read-only); None se non disponibile."""
        return await self.hass.async_add_executor_job(self._query_theft)

    def _query_theft(self) -> int | None:
        self._bind_core()
        import commands as CMD  # core/ è sul path (vedi __init__)
        return CMD.query_theft_switch()

    async def async_wake(self) -> None:
        await self.hass.async_add_executor_job(self._wake)

    def _wake(self) -> None:
        self._bind_core()
        import wake as WAKE

        def emit(m):
            _LOGGER.info("[wake] %s", m)
            self._update({"wake_status": str(m)[:255]})

        self._update({"last_wake": dt_util.utcnow()})
        # is_awake: se l'auto sta già pubblicando su MQTT non serve l'SMS.
        result = WAKE.do_wake(emit, is_awake=lambda: bool(self.data.get("awake")), send_sms=True)
        # [FALLBACK] smsAwaken inaffidabile (test 2026-06-21: A07900 due volte) → se non ha
        # svegliato l'auto, ripiega su un comando REALE (vehicleLocation), che la sveglia al
        # primo colpo e restituisce anche il GPS. A livello coordinator per non creare import
        # circolari (wake.py è importato da commands.py).
        if not (isinstance(result, dict) and result.get("online")):
            if self.data.get("awake"):
                return  # nel frattempo è arrivato un messaggio MQTT → già sveglia
            emit("Sveglia SMS non efficace → ripiego su Localizza (vehicleLocation)…")
            try:
                self._send_command("localizza")
            except Exception as err:  # noqa: BLE001 — il fallback non deve far fallire la sveglia
                emit(f"fallback Localizza fallito: {err}")

    async def async_probe(self, force: bool = False) -> None:
        await self.hass.async_add_executor_job(self._probe, force)

    def _probe(self, force: bool = False) -> None:
        self._bind_core()
        import probe as PROBE

        def emit(m):
            _LOGGER.info("[probe] %s", m)
            self._update({"probe_status": str(m)[:255]})

        # force=True (poll periodico): ignora il cooldown di 30 min della sonda.
        PROBE.probe_once(emit, force=force, on_data=self._on_probe_data)

    def _on_probe_data(self, data: dict) -> None:
        """Dati realtime (GPS/batteria/velocità/online) dalla sonda → stato posizione.

        Gira nel thread executor: gli accessi a self.position sono serializzati col
        lock e si emette sempre una COPIA (no condivisione per riferimento)."""
        patch: dict = {"realtime": dict(data) if isinstance(data, dict) else data}
        if isinstance(data, dict) and "lat" in data and "lon" in data:
            geo = {k: data[k] for k in GEO_KEYS if k in data}
            with self._state_lock:
                self.position = {**(self.position or {}), **geo}
                pos_copy = dict(self.position)
            patch["position"] = pos_copy
            patch["last_pos_fix"] = dt_util.utcnow()
        self._update(patch)

    async def async_check_session(self) -> tuple[bool, str]:
        ok, detail = await self.hass.async_add_executor_job(self._check_session)
        self._update({"session_ok": ok, "session_detail": detail})
        return ok, detail

    def _check_session(self) -> tuple[bool, str]:
        self._bind_core()
        import session as SESSION
        return SESSION.check()

    # ───────────────── recupero sessione (OTP da HA) ─────────────────
    async def async_request_otp(self) -> str:
        """Invia il codice OTP all'email dell'account (button «Richiedi OTP»)."""
        return await self.hass.async_add_executor_job(self._request_otp)

    def _request_otp(self) -> str:
        self._bind_core()
        import session as SESSION
        msgs: list[str] = []
        SESSION.request_otp(emit=msgs.append)
        detail = msgs[-1] if msgs else "richiesta inviata"
        self._update({"session_detail": detail})
        return detail

    async def async_confirm_otp(self) -> tuple[bool, str]:
        """Conia il token col codice inserito (button «Conferma OTP») e ricontrolla la sessione."""
        ok, detail = await self.hass.async_add_executor_job(self._confirm_otp, self.otp_code)
        self._update({"session_ok": ok, "session_detail": detail})
        return ok, detail

    def _confirm_otp(self, code: str) -> tuple[bool, str]:
        self._bind_core()
        import session as SESSION
        return SESSION.confirm_otp(code or "")
