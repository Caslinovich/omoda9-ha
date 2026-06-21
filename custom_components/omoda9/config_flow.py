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
import os
import sys
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN, CONF_EMAIL, CONF_PIN, CONF_VIN, CONF_TUSERID,
    CONF_BFF, CONF_TSP_HOST, CONF_CERTS_SRC, CONF_CHANNEL_ID, DEFAULTS,
)

_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)


def _pending_token_path(hass: HomeAssistant) -> str:
    """Path temporaneo dove conia il token finché non si conosce il VIN."""
    return hass.config.path(f"{DOMAIN}_pending_token.json")


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
    import session as SESSION
    msgs: list[str] = []
    ok = SESSION.request_otp(emit=msgs.append)
    return ok, (msgs[-1] if msgs else "")


def _mint_token(hass: HomeAssistant, data: dict, code: str) -> tuple[bool, str]:
    """Conia il token dal codice OTP (executor) → core.session.confirm_otp (salva nel pending)."""
    _prepare_env(hass, data)
    import session as SESSION
    return SESSION.confirm_otp(code)


def _discover(hass: HomeAssistant, data: dict) -> tuple[bool, str, list[str], str]:
    """Dopo l'OTP: scopre (tUserId, [VIN]) dal token appena coniato. Sola lettura.

    Ritorna (ok, tuserid, vins, dettaglio)."""
    _prepare_env(hass, data)
    try:
        import requests
        import omoda_auth as A
        import wake
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


def _finalize_token(hass: HomeAssistant, vin: str) -> None:
    """Sposta il token 'pending' nella token-path per-VIN definitiva."""
    pend = _pending_token_path(hass)
    dest = hass.config.path(f"{DOMAIN}_{vin}_token.json")
    try:
        if os.path.isfile(pend):
            os.replace(pend, dest)
    except OSError:
        pass


class Omoda9ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il config flow dell'integrazione (email + PIN, il resto è scoperto)."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._tuserid: str = ""
        self._vins: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            try:
                ok, _msg = await self.hass.async_add_executor_job(
                    _send_otp, self.hass, self._data
                )
            except NotImplementedError:
                return await self.async_step_otp()
            if ok:
                return await self.async_step_otp()
            errors["base"] = "otp_send_failed"

        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PIN): str,
            # Solo per regioni diverse dall'Europa / setup avanzato (default EU).
            vol.Optional(CONF_BFF, default=DEFAULTS[CONF_BFF]): str,
            vol.Optional(CONF_TSP_HOST, default=DEFAULTS[CONF_TSP_HOST]): str,
            vol.Optional(CONF_CERTS_SRC, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_otp(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok, _msg = await self.hass.async_add_executor_job(
                    _mint_token, self.hass, self._data, user_input["code"].strip()
                )
            except NotImplementedError:
                ok = True  # scaffold dev
            if ok:
                d_ok, tu, vins, _detail = await self.hass.async_add_executor_job(
                    _discover, self.hass, self._data
                )
                if not d_ok or not vins:
                    errors["base"] = "no_vehicle"
                else:
                    self._tuserid = tu
                    self._vins = vins
                    if len(vins) == 1:
                        return await self._create_entry(vins[0])
                    return await self.async_step_select_vehicle()
            else:
                errors["base"] = "otp_invalid"

        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(step_id="otp", data_schema=schema, errors=errors)

    async def async_step_select_vehicle(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return await self._create_entry(user_input[CONF_VIN])
        schema = vol.Schema({vol.Required(CONF_VIN): vol.In(self._vins)})
        return self.async_show_form(step_id="select_vehicle", data_schema=schema)

    async def _create_entry(self, vin: str):
        await self.async_set_unique_id(vin)
        self._abort_if_unique_id_configured()
        self._data[CONF_VIN] = vin
        self._data[CONF_TUSERID] = self._tuserid
        await self.hass.async_add_executor_job(_finalize_token, self.hass, vin)
        return self.async_create_entry(title=f"Omoda 9 ({vin})", data=self._data)
