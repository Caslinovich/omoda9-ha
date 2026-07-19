"""Config flow Omoda 9 / Jaecoo — login per-utente con SOLO email + PIN.

Niente più VIN/tUserId da inserire a mano: si scoprono dal backend dopo l'OTP
(`tsp/v1/app/auth/login` → tUserId, `tsp/v1/app/vmc/queryList` → VIN). Le credenziali
restano nel config_entry del SUO Home Assistant (nessun server centrale).

Flusso:
  1) user            → email, PIN (+ regione opz.) → risolve il captcha e invia l'OTP
  2) otp             → codice ricevuto via email → conia il token → scopre tUserId + VIN
  3) select_vehicle  → (solo se l'account ha più veicoli) scelta del VIN
  → crea l'entry
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PIN, CONF_VIN, CONF_TUSERID,
    CONF_BFF, CONF_TSP_HOST, CONF_CERTS_SRC, CONF_CHANNEL_ID,
    CONF_CAR_MQTT_HOST, CONF_CAR_MQTT_PORT, DEFAULTS,
    CONF_POLL_NORMAL, CONF_POLL_CHARGING,
    DEFAULT_POLL_NORMAL_MIN, DEFAULT_POLL_CHARGING_MIN,
    CONF_VEHICLE_NAME,
)

_LOGGER = logging.getLogger(__name__)

# P2-2: cartella dei moduli core/. Serve ancora come `cwd`/`OMODA_SRC_DIR` per i
# sottoprocessi di login (login_omoda.py, prova_token.py), NON più come voce di sys.path.
_CORE = os.path.join(os.path.dirname(__file__), "core")


def _clear_pin_lockout() -> None:
    """P0-2: azzera anti-lockout PIN + taskId in cache (module-level in `core/commands`).
    Da chiamare in executor a ogni riconfigurazione del PIN, anche se invariato."""
    from .core import commands  # noqa: PLC0415 — import lazy: gira in executor

    if hasattr(commands, "reset_pin_lockout"):
        commands.reset_pin_lockout()
    if hasattr(commands, "invalidate_taskid"):
        commands.invalidate_taskid()


def _pending_token_path(hass: HomeAssistant) -> str:
    """Path temporaneo dove conia il token finché non si conosce il VIN."""
    return hass.config.path(f"{DOMAIN}_pending_token.json")


def _reason_line(detail: str | None) -> str:
    """Riga col motivo del fallimento, mostrata sotto il form (vuota se non c'è). Il dettaglio è
    la coda dell'output del sottoprocesso di login (stato HTTP / chiave del server tipo
    `email.not.exists` / messaggio captcha): NON contiene PIN, OTP né token."""
    detail = (detail or "").strip()
    return f"\n\n⚠️ Motivo: {detail}" if detail else ""


def _prepare_env(hass: HomeAssistant, data: dict, token_path: str | None = None) -> None:
    """Imposta l'ambiente per i moduli core/ (letti a import-time) dai dati del flow."""
    os.environ["OMODA_EMAIL"] = data.get(CONF_EMAIL, "")
    os.environ["OMODA_PIN"] = data.get(CONF_PIN, "")
    os.environ["VIN"] = data.get(CONF_VIN, "")
    os.environ["TUSERID"] = data.get(CONF_TUSERID, "")
    os.environ["CHANNEL_ID"] = str(data.get(CONF_CHANNEL_ID, DEFAULTS[CONF_CHANNEL_ID]))
    os.environ["OMODA_BFF"] = data.get(CONF_BFF, DEFAULTS[CONF_BFF])
    os.environ["TSP_HOST"] = data.get(CONF_TSP_HOST, DEFAULTS[CONF_TSP_HOST])
    os.environ["OMODA_TOKEN_PATH"] = token_path or _pending_token_path(hass)
    os.environ["OMODA_SRC_DIR"] = _CORE


def _send_otp(hass: HomeAssistant, data: dict) -> tuple[bool, str]:
    """Risolve il captcha e invia l'OTP all'email (executor) → core.session.request_otp."""
    _prepare_env(hass, data)
    from .core import session as SESSION
    msgs: list[str] = []
    ok = SESSION.request_otp(emit=msgs.append)
    return ok, (msgs[-1] if msgs else "")


def _mint_token(hass: HomeAssistant, data: dict, code: str) -> tuple[bool, str]:
    """Conia il token dal codice OTP (executor) → core.session.confirm_otp (salva nel pending)."""
    _prepare_env(hass, data)
    from .core import session as SESSION
    return SESSION.confirm_otp(code)


def _discover(hass: HomeAssistant, data: dict) -> tuple[bool, str, list[str], str]:
    """Dopo l'OTP: scopre (tUserId, [VIN]) dal token appena coniato. Sola lettura.

    Ritorna (ok, tuserid, vins, dettaglio)."""
    _prepare_env(hass, data)
    try:
        import requests
        from .core import omoda_auth as A
        from .core import wake
        wake.TOKEN_PATH = _pending_token_path(hass)   # token appena coniato
        _ut, tu = wake._bff_login()
        if not tu:
            return False, "", [], "login backend non riuscito"
        access = wake._access_token()
        headers = A.headers_post("/tsp/v1/app/vmc/queryList", extra={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*"})
        r = requests.post(A.BFF + "/tsp/v1/app/vmc/queryList",
                          data=json.dumps({}), headers=headers, timeout=25)
        j = r.json()
        lst = j.get("data")
        vins: list[str] = []
        if isinstance(lst, list):
            for v in lst:
                if isinstance(v, dict) and v.get("vin"):
                    vins.append(str(v["vin"]))
        return True, str(tu), vins, ("ok" if vins else "nessun veicolo trovato")
    except Exception as e:  # noqa: BLE001
        return False, "", [], f"errore scoperta veicoli: {type(e).__name__}"


def _finalize_token(hass: HomeAssistant, vin: str) -> bool:
    """Sposta il token 'pending' nella token-path per-VIN definitiva.

    Ritorna True se il token è in posizione (spostato ora o già presente),
    False se lo spostamento fallisce: in tal caso il flow va fatto fallire,
    perché senza token il coordinator non potrebbe autenticarsi."""
    pend = _pending_token_path(hass)
    dest = hass.config.path(f"{DOMAIN}_{vin}_token.json")
    try:
        if os.path.isfile(pend):
            os.replace(pend, dest)
        return os.path.isfile(dest)
    except OSError as e:
        _LOGGER.error("Omoda9: impossibile spostare il token in %s: %s", dest, e)
        return False


def _cleanup_pending(hass: HomeAssistant) -> None:
    """Rimuove un eventuale *_pending_token.json orfano (OTP non andato a buon fine/abort)."""
    pend = _pending_token_path(hass)
    try:
        if os.path.isfile(pend):
            os.remove(pend)
    except OSError as e:  # noqa: BLE001
        _LOGGER.debug("Omoda9: cleanup pending token fallito: %s", e)


class Omoda9ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il config flow dell'integrazione (email + PIN, il resto è scoperto)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._tuserid: str = ""
        self._vins: list[str] = []
        self._otp_requested: bool = False   # reauth: OTP già inviato in questa sessione di flow

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "Omoda9OptionsFlow":
        return Omoda9OptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        reason = ""
        if user_input is not None:
            self._data.update(user_input)
            ok, msg = await self.hass.async_add_executor_job(
                _send_otp, self.hass, self._data
            )
            if ok:
                return await self.async_step_otp()
            errors["base"] = "otp_send_failed"
            reason = _reason_line(msg)
            _LOGGER.warning("Omoda9: invio OTP fallito: %s", msg)

        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PIN): str,
            # Solo per regioni diverse dall'Europa / setup avanzato (default EU).
            vol.Optional(CONF_BFF, default=DEFAULTS[CONF_BFF]): str,
            vol.Optional(CONF_TSP_HOST, default=DEFAULTS[CONF_TSP_HOST]): str,
            # Broker MQTT dell'auto + channel id: regione-specifici (default EU). Senza
            # questi campi un setup non-EU resterebbe agganciato al broker europeo.
            vol.Optional(CONF_CAR_MQTT_HOST, default=DEFAULTS[CONF_CAR_MQTT_HOST]): str,
            vol.Optional(CONF_CAR_MQTT_PORT, default=DEFAULTS[CONF_CAR_MQTT_PORT]): vol.Coerce(int),
            vol.Optional(CONF_CHANNEL_ID, default=DEFAULTS[CONF_CHANNEL_ID]): str,
            vol.Optional(CONF_CERTS_SRC, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors,
                                    description_placeholders={"reason": reason})

    async def async_step_otp(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        reason = ""
        if user_input is not None:
            ok, msg = await self.hass.async_add_executor_job(
                _mint_token, self.hass, self._data, user_input["code"].strip()
            )
            if ok:
                d_ok, tu, vins, detail = await self.hass.async_add_executor_job(
                    _discover, self.hass, self._data
                )
                if not d_ok or not vins:
                    # Token coniato ma nessun veicolo: il pending è inutilizzabile.
                    await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
                    errors["base"] = "no_vehicle"
                    reason = _reason_line(detail)
                    _LOGGER.warning("Omoda9: scoperta veicolo fallita: %s", detail)
                else:
                    self._tuserid = tu
                    self._vins = vins
                    if len(vins) == 1:
                        return await self._create_entry(vins[0])
                    return await self.async_step_select_vehicle()
            else:
                # OTP errato/scaduto: butta il pending eventualmente già scritto.
                await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
                errors["base"] = "otp_invalid"
                reason = _reason_line(msg)
                _LOGGER.warning("Omoda9: conferma OTP fallita: %s", msg)

        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(step_id="otp", data_schema=schema, errors=errors,
                                    description_placeholders={"reason": reason})

    async def async_step_select_vehicle(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return await self._create_entry(user_input[CONF_VIN])
        schema = vol.Schema({vol.Required(CONF_VIN): vol.In(self._vins)})
        return self.async_show_form(step_id="select_vehicle", data_schema=schema)

    async def _create_entry(self, vin: str):
        # Unicità VIN il prima possibile: appena conosciamo il VIN, prima di creare
        # l'entry. NB: per un account a VIN singolo l'OTP è già stato speso quando
        # arriviamo qui — il backend non espone il VIN prima dell'autenticazione,
        # quindi non è possibile abortire come "già configurato" prima dell'OTP.
        await self.async_set_unique_id(vin)
        try:
            self._abort_if_unique_id_configured()
        except AbortFlow:
            # VIN già configurato: il token appena coniato non serve, rimuovilo.
            await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
            raise
        self._data[CONF_VIN] = vin
        self._data[CONF_TUSERID] = self._tuserid
        ok = await self.hass.async_add_executor_job(_finalize_token, self.hass, vin)
        if not ok:
            await self.hass.async_add_executor_job(_cleanup_pending, self.hass)
            return self.async_abort(reason="token_move_failed")
        return self.async_create_entry(title=f"Omoda 9 ({vin})", data=self._data)

    # ───────────────── Riconfigurazione PIN (senza smontare l'integrazione) ─────────────────
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Cambia SOLO il PIN a 4 cifre dei comandi remoti, senza OTP.

        Il PIN non serve al login (l'OTP conia il token, il PIN firma solo i comandi) →
        correggerlo è pura scrittura in entry.data + reload. È il rimedio al «PIN comandi
        errato»: prima si doveva eliminare e riaggiungere l'integrazione."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}
        if entry is None:
            return self.async_abort(reason="reconfigure_no_entry")
        if user_input is not None:
            new_pin = (user_input.get(CONF_PIN) or "").strip()
            if not new_pin:
                errors["base"] = "pin_required"
            else:
                # chiudi un eventuale avviso "PIN errato": il reload azzera l'anti-lockout
                # (commands.reset_pin_lockout in _bind_core quando rileva il PIN cambiato).
                from homeassistant.helpers import issue_registry as ir
                ir.async_delete_issue(self.hass, DOMAIN, f"pin_wrong_{entry.entry_id}")
                # P0-2: reset INCONDIZIONATO prima del reload. `_bind_core` azzera solo
                # se il PIN è cambiato → reinserire lo STESSO PIN lasciava il blocco attivo.
                await self.hass.async_add_executor_job(_clear_pin_lockout)
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PIN: new_pin})
        # P1-5: campo PASSWORD e NESSUN default col PIN attuale. Prima il PIN comandi
        # compariva in chiaro nel form (e nello screenshot che l'utente allega al supporto):
        # è una credenziale. Si riscrive da zero, mascherato.
        schema = vol.Schema({
            vol.Required(CONF_PIN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        })
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    # ───────────────── Riautenticazione nativa (sessione morta / app ufficiale aperta) ─────────────────
    async def async_step_reauth(self, entry_data: dict[str, Any] | None = None):
        """Punto d'ingresso della reauth (HA mostra la card "Riautentica")."""
        self._otp_requested = False
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Invia un nuovo OTP e conia il token, riusando la logica del coordinator
        (`_request_otp`/`_confirm_otp`, che fanno `_bind_core` sulla token-path per-VIN).
        Campo vuoto = reinvia il codice."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.context["entry_id"])
        errors: dict[str, str] = {}
        if entry is None or coordinator is None:
            return self.async_abort(reason="reauth_no_entry")
        reason = ""
        if user_input is not None:
            code = (user_input.get("code") or "").strip()
            if code:
                ok, detail = await self.hass.async_add_executor_job(
                    coordinator._confirm_otp, code)
                if ok:
                    return self.async_update_reload_and_abort(entry, data=entry.data)
                errors["base"] = "otp_invalid"
                reason = _reason_line(detail)
                _LOGGER.warning("Omoda9: reauth, conferma OTP fallita: %s", detail)
            else:
                self._otp_requested = False   # nessun codice = richiesta di reinvio
        # (ri)invia il codice OTP la prima volta che si mostra la form (o su richiesta di reinvio)
        if not self._otp_requested:
            self._otp_requested = True
            try:
                await self.hass.async_add_executor_job(coordinator._request_otp)
            except Exception as e:  # noqa: BLE001
                errors["base"] = "otp_send_failed"
                reason = _reason_line(f"{type(e).__name__}: {e}")
                _LOGGER.warning("Omoda9: reauth, invio OTP fallito: %s", e)
        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors,
            description_placeholders={"email": entry.data.get(CONF_EMAIL, ""),
                                      "reason": reason})


class Omoda9OptionsFlow(config_entries.OptionsFlow):
    """Opzioni: i due intervalli (minuti) del poll telemetria. 0 = disattiva.

    `poll_normal_min` = a riposo/parcheggiata; `poll_charging_min` = quando l'auto è
    attaccata alla colonnina (di norma più breve, per seguire la ricarica)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opt = self._entry.options or {}
        # nome veicolo corrente (override o quello rilevato), per pre-riempire il campo
        cur_name = opt.get(CONF_VEHICLE_NAME) or self._entry.data.get(CONF_VEHICLE_NAME) or ""
        schema = vol.Schema({
            vol.Optional(
                CONF_POLL_NORMAL,
                default=opt.get(CONF_POLL_NORMAL, DEFAULT_POLL_NORMAL_MIN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
            vol.Optional(
                CONF_POLL_CHARGING,
                default=opt.get(CONF_POLL_CHARGING, DEFAULT_POLL_CHARGING_MIN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
            # override manuale del nome del veicolo (vuoto = usa quello rilevato dall'auto)
            vol.Optional(
                CONF_VEHICLE_NAME,
                description={"suggested_value": cur_name},
            ): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
