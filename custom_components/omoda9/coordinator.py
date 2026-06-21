"""Coordinator Omoda 9 — sostituisce ha_bridge.py (MQTT auto + sonda) in modo nativo.

Riceve via MQTT (mutual-TLS, paho in un thread) gli eventi 5A02 dell'auto, ne fa il
parsing (stesso identico mapping del bridge: vedi SENSORS) e tiene lo stato corrente
in `self.data`. Le entità native leggono da qui. Comandi/sveglia/sonda/sessione sono
delegati al "cuore di protocollo" in `core/` (eseguito in executor).

NB: i moduli `core/` leggono la config da env a import-time → impostiamo os.environ
DALL'entry prima di importarli (assunzione: una sola auto per istanza HA).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import ssl
import threading
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, CAR_SEED, DEFAULT_AWAKE_WINDOW, CERT_FILES,
    CONF_VIN, CONF_TUSERID, CONF_PIN, CONF_EMAIL, CONF_CERTS_SRC,
    CONF_BFF, CONF_TSP_HOST, CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, CONF_CHANNEL_ID,
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
    {"key": "sunshadeState",  "name": "Tendina tetto",       "comp": "binary_sensor", "dclass": "window", "kind": "open"},
    {"key": "frontHVACState", "name": "Clima",               "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "airPurification","name": "Purificazione aria",  "comp": "binary_sensor", "dclass": "running","kind": "onoff"},
    {"key": "frontWindshieldHeat", "name": "Sbrinamento parabrezza", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
    {"key": "fWinHeatingState","name": "Riscaldamento parabrezza", "comp": "binary_sensor", "dclass": "running", "kind": "onoff"},
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
]
META = {s["key"]: s for s in SENSORS}


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

        # env per i moduli core/ (li importeremo DOPO aver settato l'ambiente)
        os.environ.setdefault("VIN", self.vin)
        os.environ.setdefault("TUSERID", self.tuserid)
        os.environ.setdefault("CHANNEL_ID", self.channel_id)
        os.environ.setdefault("OMODA_TOKEN_PATH", self.token_path)
        os.environ.setdefault("OMODA_BFF", cfg[CONF_BFF])
        os.environ.setdefault("TSP_HOST", cfg[CONF_TSP_HOST])
        if cfg.get(CONF_PIN):
            os.environ.setdefault("OMODA_PIN", cfg[CONF_PIN])
        if cfg.get(CONF_EMAIL):
            os.environ.setdefault("OMODA_EMAIL", cfg[CONF_EMAIL])

        self._car = None  # paho mqtt.Client (importato in _connect_car, executor)
        self._fields: dict[str, str] = {}
        self._last_msg_ts: float = 0.0
        self.position: dict | None = None
        self.otp_code: str = ""   # impostato dall'entità text «Codice OTP», letto da confirm
        self.data = {"fields": self._fields, "position": None,
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
        os.makedirs(self.certs_dir, exist_ok=True)

        def _have_required() -> bool:
            return all(os.path.isfile(os.path.join(self.certs_dir, f)) for f in REQUIRED_CERTS)

        if _have_required():
            return True, "cert presenti"

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
            return False, (f"in {self.certs_src} mancano alcuni cert richiesti "
                           f"({', '.join(REQUIRED_CERTS)})")

        return False, (f"cert mutual-TLS mancanti: copia {', '.join(CERT_FILES)} in "
                       f"{self.certs_dir} (oppure indica una cartella sorgente nelle opzioni)")

    # ───────────────── ciclo di vita MQTT auto ─────────────────
    async def async_start(self) -> None:
        """Avvia la connessione MQTT all'auto (paho gira in un thread proprio)."""
        await self.hass.async_add_executor_job(self._connect_car)

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
        c.connect(self.car_host, self.car_port, keepalive=60)
        c.loop_start()
        self._car = c

    def async_stop(self) -> None:
        if self._car is not None:
            self._car.loop_stop()
            self._car.disconnect()
            self._car = None

    def _on_car_message(self, c, u, msg) -> None:
        """Parsing identico a ha_bridge.car_on_message (thread paho → push verso HA)."""
        try:
            obj = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        content = obj.get("content", obj)
        data = content.get("data", {}) if isinstance(content, dict) else {}
        now = time.time()
        now_dt = dt_util.utcnow()
        _LOGGER.debug("[auto] messaggio ricevuto: %d campi", len(data) if isinstance(data, dict) else 0)

        patch = {"last_seen": now_dt}

        # 1301 = push posizione (lat/lon) → device_tracker
        if isinstance(data, dict) and "lat" in data and "lon" in data:
            self.position = {"lat": data.get("lat"), "lon": data.get("lon"), **data}
            patch["last_pos_fix"] = now_dt

        was_awake = bool(self._last_msg_ts) and (now - self._last_msg_ts) < self.awake_window
        self._last_msg_ts = now
        for k, v in data.items():
            if k != "time":
                self._fields[k] = str(v)

        patch.update({
            "fields": dict(self._fields),
            "position": self.position,
            "awake": True,
        })
        self._update(patch)

        # fronte di risveglio → una sonda realtime (posizione/batteria), sola lettura
        if not was_awake:
            self.hass.add_job(self.async_probe())

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
        config flow li ha già importati (con VIN ignoto), i loro global resterebbero
        stale nello stesso processo. Qui li forziamo ai valori dell'entry → robusto
        rispetto all'ordine di import. Idempotente, eseguito in executor."""
        import wake, commands, probe
        wake.TOKEN_PATH = self.token_path
        wake.VIN = self.vin
        wake.TSP_HOST = self.tsp_host
        commands.VIN = self.vin
        commands.PIN = self.pin
        commands.TSP_HOST = self.tsp_host
        probe.VIN = self.vin
        os.environ["OMODA_TOKEN_PATH"] = self.token_path
        os.environ["VIN"] = self.vin

    # ───────────────── azioni (delega a core/, in executor) ─────────────────
    async def async_send_command(self, key: str) -> str:
        return await self.hass.async_add_executor_job(self._send_command, key)

    def _send_command(self, key: str) -> str:
        self._bind_core()
        import commands as CMD  # core/ è sul path (vedi __init__)
        msgs: list[str] = []

        def emit(m):
            msgs.append(str(m))
            _LOGGER.info("[cmd] %s", m)
            self._update({"cmd_status": str(m)[:255]})

        CMD.send(key, emit=emit)
        return msgs[-1] if msgs else "inviato"

    async def async_wake(self) -> None:
        await self.hass.async_add_executor_job(self._wake)

    def _wake(self) -> None:
        self._bind_core()
        import wake as WAKE

        def emit(m):
            _LOGGER.info("[wake] %s", m)
            self._update({"wake_status": str(m)[:255]})

        self._update({"last_wake": dt_util.utcnow()})
        WAKE.do_wake(emit, send_sms=True)

    async def async_probe(self) -> None:
        await self.hass.async_add_executor_job(self._probe)

    def _probe(self) -> None:
        self._bind_core()
        import probe as PROBE

        def emit(m):
            _LOGGER.info("[probe] %s", m)
            self._update({"probe_status": str(m)[:255]})

        PROBE.probe_once(emit, on_data=self._on_probe_data)

    def _on_probe_data(self, data: dict) -> None:
        """Dati realtime (GPS/batteria/velocità/online) dalla sonda → stato posizione."""
        patch: dict = {"realtime": data}
        if "lat" in data and "lon" in data:
            self.position = {**(self.position or {}), **data}
            patch["position"] = self.position
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
