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
    CONF_PHONE, CONF_AREA_CODE, DEFAULT_AREA_CODE,
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


def _clear_pin_lockout(hass: HomeAssistant, entry_id: str) -> None:
    """P0-2: azzera anti-lockout PIN + taskId in cache del veicolo interessato.

    Da chiamare a ogni riconfigurazione del PIN, ANCHE se invariato: il blocco vive in
    memoria e un reload non lo azzera, quindi reinserire lo stesso PIN (caso reale,
    quando il blocco non era colpa del PIN) lascerebbe l'utente fermo senza segnale.

    P2-6: lo stato è per-veicolo, quindi si agisce sul contesto di QUEL coordinator e
    non più su un global condiviso da tutte le auto configurate."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is not None:
        coordinator.ctx.reset_pin_lockout()


def _pending_token_path(hass: HomeAssistant) -> str:
    """Path temporaneo dove conia il token finché non si conosce il VIN."""
    return hass.config.path(f"{DOMAIN}_pending_token.json")


def _reason_line(detail: str | None) -> str:
    """Riga col motivo del fallimento, mostrata sotto il form (vuota se non c'è). Il dettaglio è
    la coda dell'output del sottoprocesso di login (stato HTTP / chiave del server tipo
    `email.not.exists` / messaggio captcha): NON contiene PIN, OTP né token."""
    detail = (detail or "").strip()
    return f"\n\n⚠️ Motivo: {detail}" if detail else ""


# Client TLS di RIPIEGO per il solo invio SMS. L'endpoint `sendSmsCode` è dietro un WAF che
# filtra sull'impronta TLS del client; la strada normale è `core/tls_client.py`, che ottiene
# l'impronta giusta con la libreria standard sopra `requests` — già nel manifest, nulla da
# scaricare, uguale su ogni processore. `curl_cffi` serve solo se un giorno quella strada
# smettesse di passare, ed è per questo che si installa **solo su richiesta**, come rimedio.
SMS_CLIENT_REQ = "curl_cffi>=0.7"


def _ripiego_gia_presente() -> bool:
    """C'è già `curl_cffi`? Se sì, non ha senso offrire di installarlo."""
    from .core import tls_client
    return tls_client.curl_cffi_presente()


async def _assicura_client_sms(hass: HomeAssistant) -> bool:
    """Installa `curl_cffi` come ULTIMA SPIAGGIA, e solo se non c'è già.

    ⚠️ Perché NON sta nei `requirements` del manifest: è un pacchetto con estensione nativa, e
    le requirements del manifest sono obbligatorie per TUTTI. Se l'installazione fallisce,
    `async_process_deps_reqs` solleva PRIMA che il componente venga importato, e l'utente non
    perde «l'SMS»: perde tutte le entità e non riesce più nemmeno ad aprire la configurazione.
    Chi usa il login e-mail pagherebbe un rischio che non lo riguarda.

    ⚠️ Perché non si chiama più all'INIZIO del login via SMS, com'era prima. Farlo lì rendeva
    obbligatorio ciò che è facoltativo, e si portava dietro quattro guai misurati:
      * dentro il container di Home Assistant il pacchetto finisce in `/root/.local/…`, che non
        è fra i volumi montati: ogni aggiornamento di HA ricrea il container e **lo cancella**,
        senza che nulla lo reinstalli (non essendo nel manifest). Il guasto si manifesta mesi
        dopo, quando serve un OTP;
      * un fallimento anche momentaneo entra nella memoria dei fallimenti di HA, che da lì in
        poi rifiuta **all'istante e senza ritentare** fino al riavvio di Home Assistant: chi
        configurava mentre il router si riavviava restava bloccato senza capire perché;
      * su un'installazione senza ambiente virtuale il pacchetto va in `<config>/deps`, che HA
        aggiunge al proprio `sys.path` ma non al `PYTHONPATH`: il sottoprocesso di login non lo
        vedrebbe comunque, e l'utente leggeva «installa curl_cffi» con curl_cffi installato;
      * il passo del form restava fermo su uno scaricamento di ~12 MB senza dirlo a nessuno.
    Ora è un rimedio: si tenta una volta sola, quando il filtro anti-bot ha respinto TUTTI i
    client disponibili, e se non riesce non blocca niente."""
    from homeassistant.requirements import async_process_requirements

    from .core import tls_client

    if tls_client.curl_cffi_presente():
        return True
    try:
        # `is_built_in=False`: senza, HA descrive omoda9 come integrazione di serie nei propri
        # avvisi e sopprime il rimando all'autore dell'integrazione personalizzata.
        await async_process_requirements(hass, DOMAIN, [SMS_CLIENT_REQ], is_built_in=False)
        return True
    except Exception as e:  # noqa: BLE001  — RequirementsNotFound e qualsiasi errore di pip
        _LOGGER.warning("Omoda9: impossibile installare %s (client TLS di ripiego per l'invio "
                        "SMS): %s", SMS_CLIENT_REQ, e)
        return False


_ACCESSO_INTERNAZIONALE = "00"   # forma lunga di "+", come si scrive sui vecchi telefoni
_MAX_CIFRE_PREFISSO = 3          # E.164: i prefissi paese hanno 1, 2 o 3 cifre. Nessuno ne ha 4.


def _normalizza_telefono(numero: str | None, prefisso: str | None) -> tuple[str, str]:
    """Ripulisce numero e prefisso UNA VOLTA SOLA, qui: da qui in poi viaggiano in entry.data,
    nell'ambiente dei sottoprocessi e nell'identità `APP-LOGIN@<num>_<area>`, e a valle nessuno
    li tocca più (`invia_sms` fa solo `lstrip("+")` + spazi, `build_params_mobile` altrettanto).

    Cose che la gente scrive davvero e che senza questo passaggio arrivano storte al server:
      * numero copiato dalla rubrica col prefisso già dentro → identità `APP-LOGIN@39<num>_39`;
      * separatori dentro il numero: spazi, punti, trattini;
      * prefisso scritto `+39` o `0039` → `areaCode="+39"`, che il server non riconosce;
      * zero di accesso nazionale davanti al numero (Regno Unito, Germania, Francia…).

    ⚠️ REGOLA CHE GOVERNA I CASI DUBBI — i due errori possibili NON si equivalgono.
    Lasciare attaccato un prefisso che andava tolto produce un tentativo fallito, e l'utente
    rimedia riscrivendo il numero. **Tagliare cifre a un numero valido no**: il valore mutilato
    viene ri-proposto nel form, l'utente lo rimanda tale e quale, e da lì in poi ogni tentativo
    parte storto; se il flow arriva in fondo il numero sbagliato finisce in `entry.data`, che
    `reconfigure` non permette di correggere (cambia solo il PIN) — resta solo eliminare e
    riaggiungere l'integrazione, perdendo entity_id e storico. Perciò **nel dubbio non si taglia**.

    ⚠️ IL PREFISSO SI SFILA SOLO SE L'UTENTE LO HA DICHIARATO, cioè se ha scritto `+` o `00`.
    Non esiste modo di distinguere altrimenti «prefisso incollato davanti» da «numero che
    comincia per quelle cifre»: sono la stessa stringa. Le due euristiche provate prima
    tagliavano numeri veri — la prima (6 cifre residue) amputava i cellulari italiani
    391/392/393, la seconda (9 cifre residue) i numeri kazaki e statunitensi, dove il prefisso
    è di UNA cifra e un nazionale da 10 supera qualunque soglia. Peggio: essendo la soglia
    calcolata sull'uscita, la funzione **non era idempotente** e il numero perdeva una cifra a
    ogni ri-apertura del form, senza che l'utente digitasse nulla.
    COSTO ACCETTATO: chi incolla `39…` senza `+` non se lo vede sfilare, il tentativo fallisce
    e deve riscrivere il numero come chiede l'etichetta del campo. È il verso giusto in cui
    sbagliare. Vale anche per i Paesi a numerazione corta (Danimarca, Norvegia).
    AMBIGUITÀ RESIDUA, dichiarata: chi scrive `+` davanti al PROPRIO numero nazionale — cioè
    senza il prefisso paese, contro quanto dice l'etichetta — e ha un numero che comincia con
    le cifre del prefisso (in Italia: 391/392/393) se le vede sfilare, perché il `+` è preso
    per quello che significa. Le due forme sono la stessa stringa e non c'è modo di
    distinguerle; il taglio avviene una volta sola e non peggiora a ogni tentativo.

    ⚠️ ORDINE: la forma internazionale (`+39…`, `0039…`) va riconosciuta PRIMA di rimuovere
    qualsiasi zero. Facendolo dopo, `0039…` non corrispondeva mai al prefisso paese e usciva
    col prefisso duplicato dentro il numero.

    ⚠️ IDEMPOTENZA, non un vezzo: dopo un invio fallito il form viene ri-proposto **coi valori
    già normalizzati**, quindi questa funzione riceve regolarmente la propria uscita. L'uscita
    non contiene più `+` né zeri iniziali, quindi nessuno dei due tagli può riscattare: è
    idempotente per costruzione, non per fortuna.

    ⚠️ FUORI PERIMETRO: i fissi italiani, che in E.164 conservano lo zero iniziale. Qui lo zero
    viene tolto sempre, perché questo campo serve a ricevere un SMS e i fissi non ne ricevono;
    i cellulari italiani non cominciano mai per zero.

    ⚠️ Niente numeri per esteso qui né altrove nel repo, nemmeno inventati: `check_secrets.sh`
    li tratta tutti come dato personale (giustamente — non sa distinguere i tuoi dagli altrui).
    Ritorna ("", "") se numero o prefisso non sono utilizzabili → il chiamante mostra
    `phone_invalid` invece di bruciare un tentativo (e un SMS) su dati inutilizzabili."""
    solo_cifre = lambda s: "".join(ch for ch in str(s or "") if ch.isdigit())

    # ── prefisso paese ───────────────────────────────────────────────────────────────────
    scritto = str(prefisso or "").strip()
    if not scritto:
        pref = DEFAULT_AREA_CODE              # casella lasciata vuota = «vale il default»
    else:
        pref = solo_cifre(scritto).lstrip("0")            # "+39" / "0039" → "39"
        # Un prefisso SCRITTO ma illeggibile ("+", "0", "abc") non deve diventare Italia in
        # silenzio: chi è in Germania si vedrebbe spedire l'SMS a un numero italiano che non è
        # suo. Prima il ripiego sul default rendeva impossibile accorgersene — e il controllo
        # `not pref` più in basso era codice morto, perché `pref` non poteva mai essere vuoto.
        if not 1 <= len(pref) <= _MAX_CIFRE_PREFISSO:
            return "", ""

    # ── numero ───────────────────────────────────────────────────────────────────────────
    grezzo = str(numero or "").strip()
    num = solo_cifre(grezzo)
    # Forma internazionale DICHIARATA dall'utente: solo allora il prefisso paese è dentro il
    # numero e si può sfilare senza rischiare di amputare (vedi la regola sopra).
    internazionale = grezzo.startswith("+") or num.startswith(_ACCESSO_INTERNAZIONALE)
    if num.startswith(_ACCESSO_INTERNAZIONALE):
        num = num[len(_ACCESSO_INTERNAZIONALE):]
    if internazionale and num.startswith(pref):
        num = num[len(pref):]

    # Zero di accesso nazionale (Regno Unito, Germania, Francia…): si scrive solo nella forma
    # interna al Paese e sparisce in E.164. Va tolto SEMPRE, non in alternativa allo sfilamento
    # del prefisso — `+44 (0)7912…` ha entrambi, e con un `elif` lo zero restava attaccato.
    # `lstrip` e non un taglio singolo: così l'uscita non comincia mai per zero, ed è questo a
    # rendere la funzione idempotente (un taglio singolo ne avrebbe tolto uno per ogni passata).
    num = num.lstrip("0")

    # E.164: numero + prefisso non superano le 15 cifre in tutto.
    if not 6 <= len(num) <= 15 - len(pref):
        return "", ""
    return num, pref


def _ctx_del_flow(hass: HomeAssistant, data: dict, token_path: str | None = None):
    """`CoreCtx` per i passi del config flow, costruito dai dati inseriti nel form.

    P2-6: prima questa funzione scriveva otto variabili in `os.environ` — PIN ed email
    compresi — che restavano nell'ambiente del processo Home Assistant. Ora la
    configurazione del tentativo in corso è un oggetto locale alla chiamata: due utenti
    che configurano due auto non si calpestano più, e nessun segreto resta in giro.

    Durante il flow il VIN non è ancora noto, quindi il token si conia in un percorso
    "pending" e viene spostato al suo posto definitivo solo a veicolo scelto."""
    from .core.context import CoreCtx

    return CoreCtx(
        vin=data.get(CONF_VIN, ""),
        tuserid=data.get(CONF_TUSERID, ""),
        pin=data.get(CONF_PIN, ""),
        email=data.get(CONF_EMAIL, ""),
        phone=data.get(CONF_PHONE, ""),
        area_code=str(data.get(CONF_AREA_CODE, DEFAULT_AREA_CODE) or DEFAULT_AREA_CODE),
        token_path=token_path or _pending_token_path(hass),
        src_dir=_CORE,
        tsp_host=data.get(CONF_TSP_HOST, DEFAULTS[CONF_TSP_HOST]),
        bff=data.get(CONF_BFF, DEFAULTS[CONF_BFF]),
        channel_id=str(data.get(CONF_CHANNEL_ID, DEFAULTS[CONF_CHANNEL_ID])),
    )


def _send_otp(hass: HomeAssistant, data: dict) -> tuple[bool, str]:
    """Risolve il captcha e invia l'OTP all'email (executor) → core.session.request_otp."""
    from .core import session as SESSION
    msgs: list[str] = []
    ok = SESSION.request_otp(_ctx_del_flow(hass, data), emit=msgs.append)
    return ok, (msgs[-1] if msgs else "")


def _mint_token(hass: HomeAssistant, data: dict, code: str) -> tuple[bool, str]:
    """Conia il token dal codice OTP (executor) → core.session.confirm_otp (salva nel pending)."""
    from .core import session as SESSION
    return SESSION.confirm_otp(_ctx_del_flow(hass, data), code)


def _discover(hass: HomeAssistant, data: dict) -> tuple[bool, str, list[str], str]:
    """Dopo l'OTP: scopre (tUserId, [VIN]) dal token appena coniato. Sola lettura.

    Ritorna (ok, tuserid, vins, dettaglio)."""
    try:
        import requests
        from .core import omoda_auth as A
        from .core import wake
        # il token è quello appena coniato, ancora nel percorso "pending"
        ctx = _ctx_del_flow(hass, data, token_path=_pending_token_path(hass))
        _ut, tu = wake._bff_login(ctx)
        if not tu:
            return False, "", [], "login backend non riuscito"
        access = wake._access_token(ctx)
        headers = A.headers_post("/tsp/v1/app/vmc/queryList", ctx=ctx, extra={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*"})
        r = requests.post(ctx.bff + "/tsp/v1/app/vmc/queryList",
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
        self._reauth_reason: str = ""       # reauth: motivo dell'ultimo tentativo, mostrato nel menu

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "Omoda9OptionsFlow":
        return Omoda9OptionsFlow(config_entry)

    def _region_fields(self) -> dict:
        """Campi opzionali di REGIONE, comuni a login email e telefono (default = Europa)."""
        return {
            # Solo per regioni diverse dall'Europa / setup avanzato (default EU).
            vol.Optional(CONF_BFF, default=DEFAULTS[CONF_BFF]): str,
            vol.Optional(CONF_TSP_HOST, default=DEFAULTS[CONF_TSP_HOST]): str,
            # Broker MQTT dell'auto + channel id: regione-specifici (default EU). Senza
            # questi campi un setup non-EU resterebbe agganciato al broker europeo.
            vol.Optional(CONF_CAR_MQTT_HOST, default=DEFAULTS[CONF_CAR_MQTT_HOST]): str,
            vol.Optional(CONF_CAR_MQTT_PORT, default=DEFAULTS[CONF_CAR_MQTT_PORT]): vol.Coerce(int),
            vol.Optional(CONF_CHANNEL_ID, default=DEFAULTS[CONF_CHANNEL_ID]): str,
            vol.Optional(CONF_CERTS_SRC, default=""): str,
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Scelta del metodo di accesso: e-mail oppure numero di telefono (SMS).

        Alcuni account Omoda/Jaecoo sono registrati col NUMERO e non hanno e-mail: per loro
        il login e-mail fallisce. Il ramo telefono manda un codice via SMS."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["login_email", "login_phone"],
        )

    async def _submit_login(self, user_input: dict[str, Any], step_id: str, schema):
        """Logica comune ai due login: salva i dati, prova a inviare l'OTP, va allo step OTP."""
        self._data.update(user_input)
        ok, msg = await self.hass.async_add_executor_job(_send_otp, self.hass, self._data)
        if ok:
            return await self.async_step_otp()
        _LOGGER.warning("Omoda9: invio OTP fallito: %s", msg)
        # Ripropone quanto già digitato: senza questo i campi tornano vuoti e — peggio — i
        # parametri di REGIONE tornano ai default europei. Un utente fuori dall'Europa che
        # non se ne accorge riprova con gli endpoint sbagliati, e se poi riesce si ritrova
        # l'entry creato con quelli.
        # ⚠️ Il PIN NO. `add_suggested_values_to_schema` riempie ogni chiave che trova, e il
        # campo del PIN è un `str` normale, non un campo password: ri-proponendolo lo si
        # rimanda a schermo in chiaro. Il resto del file tratta il PIN come credenziale da non
        # far ricomparire nel form (vedi il passo di riconfigurazione), qui la cautela mancava.
        schema = self.add_suggested_values_to_schema(
            schema, {k: v for k, v in user_input.items() if k != CONF_PIN})
        return self.async_show_form(step_id=step_id, data_schema=schema,
                                    errors={"base": "otp_send_failed"},
                                    description_placeholders={"reason": _reason_line(msg)})

    async def async_step_login_email(self, user_input: dict[str, Any] | None = None):
        """Login via e-mail (comportamento storico)."""
        schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PIN): str,
            **self._region_fields(),
        })
        if user_input is not None:
            return await self._submit_login(user_input, "login_email", schema)
        return self.async_show_form(step_id="login_email", data_schema=schema,
                                    description_placeholders={"reason": ""})

    async def async_step_login_phone(self, user_input: dict[str, Any] | None = None):
        """Login via SMS: numero di telefono + prefisso internazionale (Italia = 39)."""
        schema = vol.Schema({
            vol.Required(CONF_PHONE): str,
            vol.Required(CONF_AREA_CODE, default=DEFAULT_AREA_CODE): str,
            vol.Required(CONF_PIN): str,
            **self._region_fields(),
        })
        if user_input is not None:
            user_input = dict(user_input)
            numero, prefisso = _normalizza_telefono(
                user_input.get(CONF_PHONE), user_input.get(CONF_AREA_CODE))
            if not numero or not prefisso:
                return self.async_show_form(
                    step_id="login_phone",
                    # PIN escluso: è una credenziale e il campo non è di tipo password.
                    data_schema=self.add_suggested_values_to_schema(
                        schema, {k: v for k, v in user_input.items() if k != CONF_PIN}),
                    errors={"base": "phone_invalid"},
                    description_placeholders={"reason": ""})
            user_input[CONF_PHONE], user_input[CONF_AREA_CODE] = numero, prefisso
            return await self._submit_login(user_input, "login_phone", schema)
        return self.async_show_form(step_id="login_phone", data_schema=schema,
                                    description_placeholders={"reason": ""})

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
    def _entry_da_riconfigurare(self):
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def _applica_riconfigurazione(self, entry, dati: dict):
        """Scrive i dati nuovi e ricarica l'integrazione.

        Il reset del blocco anti-PIN sta qui e non nel solo passo del PIN perché il reload
        avviene comunque: farlo in un ramo solo lascerebbe il blocco attivo dopo un cambio di
        metodo, che è proprio il momento in cui si sta cercando di rimettere in piedi l'accesso."""
        from homeassistant.helpers import issue_registry as ir
        ir.async_delete_issue(self.hass, DOMAIN, f"pin_wrong_{entry.entry_id}")
        # P0-2: reset INCONDIZIONATO prima del reload. `_bind_core` azzera solo se il PIN è
        # cambiato → reinserire lo STESSO PIN lasciava il blocco attivo.
        _clear_pin_lockout(self.hass, entry.entry_id)
        return self.async_update_reload_and_abort(entry, data=dati)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Menu di «Configura»: cosa si vuole correggere, senza toccare il resto.

        ⚠️ È un MENU e non un unico modulo, e la ragione è pratica: chi entra qui per cambiare
        il modo in cui riceve il codice non deve trovarsi a dover ridigitare il PIN dei comandi,
        che non c'entra nulla e che — essendo una credenziale — non può essere pre-riempito nel
        form. Separando i passi, ogni schermata chiede soltanto ciò che si sta cambiando.

        Le tre voci coprono i tre guasti reali visti sul campo:
          * il PIN dei comandi sbagliato (i comandi risultano riusciti e l'auto non fa nulla);
          * il numero di telefono cambiato o digitato male — prima l'unica via era eliminare e
            riaggiungere l'integrazione, perdendo entity_id e storico di oltre cento entità;
          * l'account registrato con un canale diverso da quello con cui è stata configurata
            l'integrazione: la riautenticazione offre SOLO il canale configurato, quindi senza
            questo passo non c'era modo di passare dall'e-mail all'SMS o viceversa."""
        entry = self._entry_da_riconfigurare()
        if entry is None:
            return self.async_abort(reason="reconfigure_no_entry")
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_pin", "reconfigure_email", "reconfigure_phone"],
        )

    async def async_step_reconfigure_pin(self, user_input: dict[str, Any] | None = None):
        """Cambia il PIN a 4 cifre dei comandi remoti, senza OTP.

        Il PIN non serve al login (l'OTP conia il token, il PIN firma solo i comandi) →
        correggerlo è pura scrittura in entry.data + reload."""
        entry = self._entry_da_riconfigurare()
        errors: dict[str, str] = {}
        if entry is None:
            return self.async_abort(reason="reconfigure_no_entry")
        if user_input is not None:
            new_pin = (user_input.get(CONF_PIN) or "").strip()
            if not new_pin:
                errors["base"] = "pin_required"
            else:
                return self._applica_riconfigurazione(
                    entry, {**entry.data, CONF_PIN: new_pin})
        # P1-5: campo PASSWORD e NESSUN default col PIN attuale. Prima il PIN comandi
        # compariva in chiaro nel form (e nello screenshot che l'utente allega al supporto):
        # è una credenziale. Si riscrive da zero, mascherato.
        return self.async_show_form(
            step_id="reconfigure_pin", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_PIN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }))

    async def async_step_reconfigure_email(self, user_input: dict[str, Any] | None = None):
        """Passa a ricevere il codice via e-mail (o corregge l'indirizzo).

        ⚠️ Il numero viene SVUOTATO, non lasciato lì: il canale attivo è «telefono se c'è un
        numero, altrimenti e-mail» (`core/session._is_phone`), quindi un numero dimenticato in
        configurazione continuerebbe a dirottare l'invio dell'OTP sull'SMS. L'indirizzo invece
        resta salvato anche quando si sceglie l'SMS, così tornare indietro è a due tap."""
        entry = self._entry_da_riconfigurare()
        errors: dict[str, str] = {}
        if entry is None:
            return self.async_abort(reason="reconfigure_no_entry")
        if user_input is not None:
            indirizzo = (user_input.get(CONF_EMAIL) or "").strip()
            if "@" not in indirizzo or "." not in indirizzo.rpartition("@")[2]:
                errors["base"] = "email_invalid"
            else:
                return self._applica_riconfigurazione(entry, {
                    **entry.data, CONF_EMAIL: indirizzo,
                    CONF_PHONE: "", CONF_AREA_CODE: "",
                })
        return self.async_show_form(
            step_id="reconfigure_email", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL,
                             default=entry.data.get(CONF_EMAIL, "")): str,
            }))

    async def async_step_reconfigure_phone(self, user_input: dict[str, Any] | None = None):
        """Passa a ricevere il codice via SMS (o corregge il numero).

        Il numero passa dalla STESSA normalizzazione del primo accesso: è il punto unico di
        pulizia, e farne una seconda copia qui vorrebbe dire vederle divergere.

        NB: cambiare canale non tocca il token in corso — la sessione resta valida finché non
        scade. Cambia solo dove arriverà il prossimo codice. E se il numero non risulta
        associato all'account Omoda, l'invio fallirà con un messaggio esplicito: si torna
        all'e-mail da questo stesso menu, senza aver perso niente."""
        entry = self._entry_da_riconfigurare()
        errors: dict[str, str] = {}
        if entry is None:
            return self.async_abort(reason="reconfigure_no_entry")
        if user_input is not None:
            numero, prefisso = _normalizza_telefono(
                user_input.get(CONF_PHONE), user_input.get(CONF_AREA_CODE))
            if not numero:
                errors["base"] = "phone_invalid"
            else:
                return self._applica_riconfigurazione(entry, {
                    **entry.data, CONF_PHONE: numero, CONF_AREA_CODE: prefisso,
                })
        # Il numero attuale SÌ come valore predefinito, a differenza del PIN: non è una
        # credenziale, e chi entra qui per cambiarne una cifra deve poter vedere da dove parte
        # invece di riscriverlo a memoria.
        schema = vol.Schema({
            vol.Required(CONF_PHONE, default=entry.data.get(CONF_PHONE, "")): str,
            vol.Required(CONF_AREA_CODE,
                         default=entry.data.get(CONF_AREA_CODE) or DEFAULT_AREA_CODE): str,
        })
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="reconfigure_phone", data_schema=schema, errors=errors)

    # ───────────────── Riautenticazione nativa (sessione morta / app ufficiale aperta) ─────────────────
    # REGOLA: aprire questa pagina non manda MAI un codice. L'OTP parte solo quando
    # l'utente sceglie esplicitamente «Inviami un codice nuovo».
    #
    # Prima l'invio era implicito nell'apertura del flow, e il flow si ricrea a OGNI
    # avvio di Home Assistant finché la sessione è morta: riavviare HA tre volte voleva
    # dire tre mail non richieste. Peggio, non c'era modo di chiedere un codice fresco —
    # il reinvio era nascosto dietro «lascia il campo vuoto e invia», ma il campo è
    # obbligatorio e il frontend rifiuta l'invio: vicolo cieco, con in mano solo un
    # codice ormai scaduto.
    async def async_step_reauth(self, entry_data: dict[str, Any] | None = None):
        """Punto d'ingresso della reauth (HA mostra la card "Riautentica")."""
        self._reauth_reason = ""
        return await self.async_step_reauth_confirm()

    def _reauth_targets(self):
        """(entry, coordinator) del veicolo da riautenticare, (None, None) se spariti."""
        entry_id = self.context.get("entry_id", "")
        return (self.hass.config_entries.async_get_entry(entry_id),
                self.hass.data.get(DOMAIN, {}).get(entry_id))

    @staticmethod
    def _login_identity(entry) -> str:
        """Dove arriva il codice: e-mail oppure numero (+prefisso) per gli account SMS.

        ⚠️ MASCHERATO. Questa stringa riempie i dialoghi di riautenticazione, cioè le
        schermate su cui l'utente è bloccato quando chiede aiuto — quindi proprio quelle che
        finiscono negli screenshot allegati alle issue. `coordinator._num_avviso` maschera lo
        stesso dato per quel motivo esplicito; qui usciva per esteso, e la regola dichiarata
        veniva disattesa nel file che la introduce. Le ultime 4 cifre bastano a riconoscere
        «è il mio»."""
        from .core import mask
        phone = entry.data.get(CONF_PHONE, "")
        if phone:
            return mask.numero_con_prefisso(
                phone, entry.data.get(CONF_AREA_CODE, DEFAULT_AREA_CODE))
        return mask.indirizzo_email(entry.data.get(CONF_EMAIL, ""))

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Menu della riautenticazione: due strade esplicite, nessun effetto collaterale.

        È anche il punto di ritorno dopo un codice sbagliato o un invio fallito: da qui
        si può SEMPRE chiedere un codice nuovo, quindi non si resta mai in trappola."""
        entry, coordinator = self._reauth_targets()
        if entry is None or coordinator is None:
            return self.async_abort(reason="reauth_no_entry")
        # La terza voce compare SOLO agli account SMS e SOLO se il ripiego non c'è già: è un
        # rimedio, non un passaggio obbligato, e va offerto come scelta esplicita perché costa
        # uno scaricamento. Prima l'installazione partiva da sola all'inizio del login e del
        # reauth, ed era la radice di una fila di guasti (vedi `_assicura_client_sms`).
        opzioni = ["send_code", "enter_code"]
        # In executor: `import curl_cffi` costa ~0,13 s e caricherebbe una libreria nativa da
        # 38 MB dentro il loop degli eventi, a ogni apertura del menu. I guard-rail di Home
        # Assistant non lo segnalerebbero (intercettano `importlib.import_module`, non
        # l'istruzione `import`), quindi sarebbe un blocco reale e invisibile.
        if entry.data.get(CONF_PHONE) and not await self.hass.async_add_executor_job(
                _ripiego_gia_presente):
            opzioni.append("install_fallback")
        return self.async_show_menu(
            step_id="reauth_confirm",
            menu_options=opzioni,
            description_placeholders={"email": self._login_identity(entry),
                                      "reason": self._reauth_reason},
        )

    async def async_step_install_fallback(self, user_input: dict[str, Any] | None = None):
        """Installa il client TLS di ripiego, su richiesta esplicita dell'utente.

        Serve solo nel caso in cui il filtro anti-bot del server abbia respinto tutti i client
        che il componente sa usare da solo. Qualunque sia l'esito si torna al menu con una
        frase che lo dice: non si resta mai bloccati qui."""
        ok = await _assicura_client_sms(self.hass)
        self._reauth_reason = _reason_line(
            "client TLS di ripiego installato: prova di nuovo a farti mandare il codice" if ok
            else "non è stato possibile installare il client TLS di ripiego su questo sistema "
                 "(spesso è la rete: riprova più tardi, oppure riavvia Home Assistant se "
                 "l'errore si ripete identico)")
        return await self.async_step_reauth_confirm()

    async def async_step_send_code(self, user_input: dict[str, Any] | None = None):
        """Invia un codice OTP nuovo — SOLO su gesto esplicito dell'utente."""
        _entry, coordinator = self._reauth_targets()
        if coordinator is None:
            return self.async_abort(reason="reauth_no_entry")
        try:
            ok, detail = await self.hass.async_add_executor_job(coordinator._request_otp)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        if not ok:
            # Si torna al menu con il motivo in chiaro: riprovare è a un tap.
            self._reauth_reason = _reason_line(detail)
            _LOGGER.warning("Omoda9: reauth, invio OTP fallito: %s", detail)
            return await self.async_step_reauth_confirm()
        self._reauth_reason = ""
        return await self.async_step_enter_code()

    async def async_step_enter_code(self, user_input: dict[str, Any] | None = None):
        """Inserimento del codice ricevuto via email (nessun invio implicito qui)."""
        entry, coordinator = self._reauth_targets()
        if entry is None or coordinator is None:
            return self.async_abort(reason="reauth_no_entry")
        errors: dict[str, str] = {}
        if user_input is not None:
            code = (user_input.get("code") or "").strip()
            if code:
                ok, detail = await self.hass.async_add_executor_job(
                    coordinator._confirm_otp, code)
                if ok:
                    return self.async_update_reload_and_abort(entry, data=entry.data)
                # Codice sbagliato o scaduto → torna al menu, dove «Inviami un codice
                # nuovo» è a portata di tap. Restare su questa form significherebbe
                # ricreare il vicolo cieco di prima.
                self._reauth_reason = _reason_line(detail)
                _LOGGER.warning("Omoda9: reauth, conferma OTP fallita: %s", detail)
                return await self.async_step_reauth_confirm()
            errors["code"] = "otp_required"
        schema = vol.Schema({vol.Required("code"): str})
        return self.async_show_form(
            step_id="enter_code", data_schema=schema, errors=errors,
            description_placeholders={"email": self._login_identity(entry),
                                      "reason": self._reauth_reason})


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
