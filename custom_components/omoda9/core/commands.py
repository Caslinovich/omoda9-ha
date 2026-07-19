#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
commands.py — Catalogo + invio dei comandi auto Omoda 9 (tspconsole EU REST).

Riusa la catena verificata in S24:
  - userToken via  wake._bff_login()      (token OTP in token.json, refresh automatico)
  - firma          tsp_sign.sign_body()   (base64(sha256(base)).upper())
  - taskId         get_taskid()           (env TASKID -> file piggyback -> checkPassword auto-coniato)

POST  https://tspconsole-eu.cheryinternational.com/asc/vehicleControl/<endpoint>
Header: Authorization=<userToken>, timestamp=<ms>, Content-Type=application/json; charset=utf-8,
        User-Agent=okhttp/4.9.2

⚠️  Ogni send() col taskId valido ATTUA sull'auto. È pensato per essere invocato SOLO
    dal tap di Rino su un pulsante in Home Assistant (= suo consenso esplicito).
    Catalogo body ricostruito 1:1 dagli envelope reali in
    /root/omoda9_capture_20260620/command_envelopes.txt.
"""
import os
import json
import time
import logging
import hashlib
import threading
import urllib.request
import urllib.error

_LOGGER = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))

# P2-2: import relativi di pacchetto (prima: nomi nudi + `sys.path.insert(HERE)`).
from . import wake
from . import tsp_sign
from . import omoda_auth as A
from . import codes
from .pin_lockout import PinLockout, PinLockedError
# H8: rimosso `importlib.reload(tsp_sign)` a import-time (side-effect inutile; tsp_sign
# non viene mutato altrove e ricaricarlo all'import poteva azzerare eventuali monkeypatch).

# Dati PER-ACCOUNT: nessun default — forniti via omoda9.env (vedi omoda9.env.example).
VIN        = os.environ.get("VIN", "")
PIN        = os.environ.get("OMODA_PIN", "")
TSP_HOST   = os.environ.get("TSP_HOST", "https://tspconsole-eu.cheryinternational.com")   # regione (default EU)
TASKID_FILE = os.environ.get("OMODA_TASKID_FILE", os.path.join(HERE, "data", "taskid.txt"))
MINT_TASKID = os.environ.get("OMODA_MINT_TASKID", "1") not in ("0", "", "false", "no")

# ───────────────────────── Catalogo comandi ─────────────────────────
# Ogni voce: key -> {endpoint, body(fissi specifici), name, icon, group}
# I campi comuni (clientType/seq/taskId/vin/appId/sign) li aggiunge send().
COMMANDS = [
    # — Clima —
    # clima ON/OFF: temperatura e durata sono PARAMETRICHE (le passa la climate entity via
    # `params`); i valori nel body sono solo i default se invocato senza override.
    ("clima_on",  {"endpoint": "airControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Clima acceso", "icon": "mdi:air-conditioner", "group": "Clima"}),
    ("clima_off", {"endpoint": "airControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Clima spento", "icon": "mdi:air-conditioner", "group": "Clima"}),
    ("defrost_parabrezza", {"endpoint": "frontWindshieldControl",
                   "body": {"frontWindshieldHeat": "1", "times": "15"},
                   "name": "Sbrina parabrezza", "icon": "mdi:car-defrost-front", "group": "Clima"}),
    ("defrost_parabrezza_off", {"endpoint": "frontWindshieldControl",
                   "body": {"frontWindshieldHeat": "0"},
                   "name": "Sbrina parabrezza OFF", "icon": "mdi:car-defrost-front", "group": "Clima"}),
    ("defrost_lunotto", {"endpoint": "backDefrostingControl",
                   "body": {"backDefrosting": "1", "times": "15"},
                   "name": "Sbrina lunotto", "icon": "mdi:car-defrost-rear", "group": "Clima"}),
    ("defrost_lunotto_off", {"endpoint": "backDefrostingControl",
                   "body": {"backDefrosting": "0"},
                   "name": "Sbrina lunotto OFF", "icon": "mdi:car-defrost-rear", "group": "Clima"}),
    ("volante_caldo", {"endpoint": "steeringWheelControl",
                   "body": {"controlType": "1"},
                   "name": "Volante riscaldato", "icon": "mdi:steering", "group": "Clima"}),
    ("volante_caldo_off", {"endpoint": "steeringWheelControl",
                   "body": {"controlType": "0"},
                   "name": "Volante riscaldato OFF", "icon": "mdi:steering", "group": "Clima"}),
    ("sedile_guida_caldo", {"endpoint": "seatControl",
                   "body": {"mSeatHeating": "3", "times": "15"},
                   "name": "Sedile guida riscaldato", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_guida_caldo_off", {"endpoint": "seatControl",
                   "body": {"mSeatHeating": "0"},
                   "name": "Sedile guida riscaldato OFF", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_guida_aria", {"endpoint": "seatControl",
                   "body": {"mSeatAiry": "3", "times": "15"},
                   "name": "Sedile guida ventilato", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_guida_aria_off", {"endpoint": "seatControl",
                   "body": {"mSeatAiry": "0"},
                   "name": "Sedile guida ventilato OFF", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    # Sedili passeggero e posteriori — stesso endpoint singolo `seatControl`, parametri
    # confermati dal bean CVSeatControlReqBean (p=passeggero, bl=post.SX, br=post.DX).
    # Posteriore centrale: il bean NON ha un parametro dedicato → nessun comando.
    ("sedile_passeggero_caldo", {"endpoint": "seatControl",
                   "body": {"pSeatHeating": "3", "times": "15"},
                   "name": "Sedile passeggero riscaldato", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_passeggero_caldo_off", {"endpoint": "seatControl",
                   "body": {"pSeatHeating": "0"},
                   "name": "Sedile passeggero riscaldato OFF", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_passeggero_aria", {"endpoint": "seatControl",
                   "body": {"pSeatAiry": "3", "times": "15"},
                   "name": "Sedile passeggero ventilato", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_passeggero_aria_off", {"endpoint": "seatControl",
                   "body": {"pSeatAiry": "0"},
                   "name": "Sedile passeggero ventilato OFF", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_post_sx_caldo", {"endpoint": "seatControl",
                   "body": {"blSeatHeating": "3", "times": "15"},
                   "name": "Sedile post. SX riscaldato", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_post_sx_caldo_off", {"endpoint": "seatControl",
                   "body": {"blSeatHeating": "0"},
                   "name": "Sedile post. SX riscaldato OFF", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_post_sx_aria", {"endpoint": "seatControl",
                   "body": {"blSeatAiry": "3", "times": "15"},
                   "name": "Sedile post. SX ventilato", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_post_sx_aria_off", {"endpoint": "seatControl",
                   "body": {"blSeatAiry": "0"},
                   "name": "Sedile post. SX ventilato OFF", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_post_dx_caldo", {"endpoint": "seatControl",
                   "body": {"brSeatHeating": "3", "times": "15"},
                   "name": "Sedile post. DX riscaldato", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_post_dx_caldo_off", {"endpoint": "seatControl",
                   "body": {"brSeatHeating": "0"},
                   "name": "Sedile post. DX riscaldato OFF", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_post_dx_aria", {"endpoint": "seatControl",
                   "body": {"brSeatAiry": "3", "times": "15"},
                   "name": "Sedile post. DX ventilato", "icon": "mdi:car-seat-cooler", "group": "Clima"}),
    ("sedile_post_dx_aria_off", {"endpoint": "seatControl",
                   "body": {"brSeatAiry": "0"},
                   "name": "Sedile post. DX ventilato OFF", "icon": "mdi:car-seat-cooler", "group": "Clima"}),

    # — Clima: macro comfort "tutto" (coolingControl/heatingControl) —
    # Preset unico che accende clima + TUTTI i sedili (+ sbrinatori e volante per il caldo)
    # in un colpo solo. Body ricostruito 1:1 dagli envelope reali dell'app in
    # 30_capture/omoda9_capture_20260620/command_envelopes.txt. NB: usano `duration` (NON
    # `times`); valori sedile 3=on/0=off; temperatura 15.0 (max freddo) / 31.0 (max caldo).
    # ⚠️ IMPORTANTE (verificato dal vivo 2026-06-21): questi comandi — come TUTTI i comfort —
    # vengono rifiutati dall'auto con timeout se la vettura è ACCESA/occupata (blocco di
    # sicurezza). A motore spento funzionano e accendono tutti i moduli. Non è un problema
    # del comando: a auto spenta clima+sedili+volante+parabrezza+lunotto rispondono tutti ✅.
    ("clima_raffredda_on", {"endpoint": "coolingControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "15.0", "duration": "15",
                            "mSeatAiry": "3", "pSeatAiry": "3", "blSeatAiry": "3", "brSeatAiry": "3"},
                   "name": "Raffredda tutto", "icon": "mdi:snowflake", "group": "Clima"}),
    ("clima_raffredda_off", {"endpoint": "coolingControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "15.0", "duration": "15",
                            "mSeatAiry": "0", "pSeatAiry": "0", "blSeatAiry": "0", "brSeatAiry": "0"},
                   "name": "Raffredda tutto OFF", "icon": "mdi:snowflake-off", "group": "Clima"}),
    ("clima_riscalda_on", {"endpoint": "heatingControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "31.0", "duration": "15",
                            "frontWindshieldHeat": "1", "backDefrosting": "1", "steerWheelHeatSwitch": "1",
                            "mSeatHeating": "3", "pSeatHeating": "3", "blSeatHeating": "3", "brSeatHeating": "3"},
                   "name": "Riscalda tutto", "icon": "mdi:heat-wave", "group": "Clima"}),
    ("clima_riscalda_off", {"endpoint": "heatingControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "31.0", "duration": "15",
                            "frontWindshieldHeat": "0", "backDefrosting": "0", "steerWheelHeatSwitch": "0",
                            "mSeatHeating": "0", "pSeatHeating": "0", "blSeatHeating": "0", "brSeatHeating": "0"},
                   "name": "Riscalda tutto OFF", "icon": "mdi:heat-wave", "group": "Clima"}),

    # — Porte / chiusure —
    ("sblocca",   {"endpoint": "lockControl", "body": {"lockType": "1"},
                   "name": "Sblocca porte", "icon": "mdi:lock-open-variant", "group": "Accessi"}),
    ("blocca",    {"endpoint": "lockControl", "body": {"lockType": "0"},
                   "name": "Blocca porte", "icon": "mdi:lock", "group": "Accessi"}),
    ("baule_apri",  {"endpoint": "powerLiftgateControl", "body": {"controlType": "1"},
                   "name": "Apri baule", "icon": "mdi:car-back", "group": "Accessi"}),
    ("baule_chiudi", {"endpoint": "powerLiftgateControl", "body": {"controlType": "0"},
                   "name": "Chiudi baule", "icon": "mdi:car-back", "group": "Accessi"}),

    # — Finestrini / tetto —
    ("finestrini_apri",   {"endpoint": "windowControl", "body": {"controlType": "1"},
                   "name": "Apri finestrini", "icon": "mdi:car-door", "group": "Finestrini e tetto"}),
    ("finestrini_chiudi", {"endpoint": "windowControl", "body": {"controlType": "0"},
                   "name": "Chiudi finestrini", "icon": "mdi:car-door", "group": "Finestrini e tetto"}),
    ("finestrini_ventila", {"endpoint": "windowControl", "body": {"controlType": "2"},
                   "name": "Ventila finestrini", "icon": "mdi:weather-windy", "group": "Finestrini e tetto"}),
    ("tetto_apri",   {"endpoint": "skylightControl", "body": {"controlType": "1", "skylightType": "1"},
                   "name": "Apri tetto", "icon": "mdi:car-select", "group": "Finestrini e tetto"}),
    ("tetto_chiudi", {"endpoint": "skylightControl", "body": {"controlType": "0", "skylightType": "1"},
                   "name": "Chiudi tetto", "icon": "mdi:car-select", "group": "Finestrini e tetto"}),

    # — Ricarica EV —
    # Ricarica IMMEDIATA avvio/stop (endpoint chargeStartStopControl, bean CVChargeStartStopBean
    # → solo `controlType`; 1=avvia, 0=ferma, stessa convenzione di tutti i *Control).
    ("ricarica_start", {"endpoint": "chargeStartStopControl", "body": {"controlType": "1"},
                   "name": "Avvia ricarica", "icon": "mdi:battery-charging", "group": "Ricarica"}),
    ("ricarica_stop", {"endpoint": "chargeStartStopControl", "body": {"controlType": "0"},
                   "name": "Ferma ricarica", "icon": "mdi:battery-off", "group": "Ricarica"}),
    # Ricarica PROGRAMMATA (chargeAppointControl) — body con ARRAY annidato `chargeAppointPlans`
    # (la firma annidata è risolta in tsp_sign, verificata su 4/4 envelope reali). mainSwitch =
    # interruttore generale; il piano (orario/durata/giorni) lo passa l'entità via `params`.
    # cycleData [1..7] = giorni; startTime/timeConsuming in MINUTI; switchStatus = piano attivo.
    ("ricarica_prog_on", {"endpoint": "chargeAppointControl",
                   "body": {"mainSwitch": 1, "chargeAppointPlans": [
                       {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": 480,
                        "switchStatus": 1, "timeConsuming": 360}]},
                   "name": "Ricarica programmata ON", "icon": "mdi:calendar-clock", "group": "Ricarica"}),
    ("ricarica_prog_off", {"endpoint": "chargeAppointControl",
                   "body": {"mainSwitch": 0, "chargeAppointPlans": [
                       {"cycleData": [1, 2, 3, 4, 5, 6, 7], "startTime": 480,
                        "switchStatus": 0, "timeConsuming": 360}]},
                   "name": "Ricarica programmata OFF", "icon": "mdi:calendar-remove", "group": "Ricarica"}),

    # — Altro —
    ("trova_auto", {"endpoint": "findCar", "body": {},
                   "name": "Trova auto (lampeggio)", "icon": "mdi:car-search", "group": "Altro"}),
    # NB: remoteStart (avvio motore da remoto) RIMOSSO: provato dal vivo (2026-06-21) →
    # l'auto risponde A00084 "No vehicle control command permission" (permesso negato per
    # questo veicolo). Inutile esporre un pulsante che fallisce sempre. Il bean
    # CVRemoteStartReqBean (senza campi) resta noto se in futuro il permesso cambiasse.
    # Richiesta posizione GPS: NON attua nulla; l'auto risponde con un push MQTT serviceType 1301
    # (lat/lon) che il bridge cabla nel device_tracker. È il metodo dell'app per la posizione a riposo.
    ("localizza", {"endpoint": "vehicleLocation", "body": {},
                   "name": "Localizza auto (GPS)", "icon": "mdi:crosshairs-gps", "group": "Altro"}),

    # — Sicurezza — Antifurto (theftAlarm). Avvisi+sirena per movimento non autorizzato,
    # scasso porte, rottura finestrini (descr. ufficiale app). NB: vive su /act (NON
    # /asc/vehicleControl) → usa la chiave `path` invece di `endpoint`. Body = theftAlarmSwitch
    # 0/1; send() aggiunge clientType/seq/vin e il taskId coniato (il backend lo pretende:
    # A00643 senza). Stato leggibile via query_theft_switch() (/act/theftAlarm/querySwitch).
    ("antifurto_on",  {"path": "/act/theftAlarm/setSwitch", "body": {"theftAlarmSwitch": "1"},
                   "name": "Antifurto acceso", "icon": "mdi:shield-car", "group": "Sicurezza"}),
    ("antifurto_off", {"path": "/act/theftAlarm/setSwitch", "body": {"theftAlarmSwitch": "0"},
                   "name": "Antifurto spento", "icon": "mdi:shield-off-outline", "group": "Sicurezza"}),
]
CMD_MAP = {k: v for k, v in COMMANDS}

# Codici risposta tspconsole → testo leggibile: ora dalla mappa UNICA core/codes.py.
CODE_MEANING = codes.CODE_MEANING

# Esito comando: il backend risponde SEMPRE HTTP 200, l'esito vero è nel `code` del body.
# `SUCCESS_CODES` = comando accettato dal backend (poi l'auto conferma via MQTT 110x);
# `FAILURE_CODES` = comando NON eseguito (auto occupata/a riposo, permesso negato, taskId
# o token non validi). Distinguere i due è ciò che permette alle entità ottimistiche di
# NON mostrare un finto "successo" quando l'auto ha rifiutato (vedi Omoda9OptimisticMixin).
SUCCESS_CODES = frozenset({"000000", "A00079"})
FAILURE_CODES = frozenset({
    "A00082",  # auto occupata (transitorio, riprovabile)
    "A00084",  # comando non consentito su questa auto
    "A00089", "A00546", "A00567",  # taskId/checkPassword non validi
    "A00000",  # token scaduto/non valido
    "A07312",  # rate-limit sveglia
    "A07900",  # auto a riposo / firma o car_token non validi
})
# Codici transitori: il comando può andare a buon fine se ritentato (auto solo occupata).
RETRYABLE_CODES = frozenset({"A00082"})


class CommandError(Exception):
    """Comando rifiutato dal backend/auto (NON eseguito). `code` = codice tspconsole,
    `retryable` = True se ritentare ha senso (es. auto occupata). Il coordinator lo
    lascia propagare; l'entità ottimistica lo cattura per annullare lo stato ottimistico
    e mostrare l'errore reale all'utente, invece di restare bloccata su un finto successo.

    `reason` instrada il RIMEDIO nel coordinator (routing per causa, non solo per codice):
      - "pin"    = PIN comandi errato / anti-lockout / PIN mancante → riconfigurare il PIN
                   (Repair issue fixabile / Configura → Riconfigura). NON è un problema di
                   sessione: il token è valido, i sensori funzionano.
      - "reauth" = sessione/token scaduti (login fallito, code A00000) → riautenticazione
                   nativa HA (nuovo OTP). L'OTP NON cambia il PIN: i due canali sono distinti.
      - "config" = rifiuto NON imputabile al PIN né alla sessione (permessi veicolo, richiesta
                   malformata, conio taskId disattivato): nessun rimedio automatico, solo
                   avviso. Non apre il Repair PIN e non conta per l'anti-lockout.
      - None     = altro rifiuto dell'auto (occupata, non consentito, a riposo): solo avviso."""

    def __init__(self, message: str, code: str | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.retryable = code in RETRYABLE_CODES

# H6/P0-1/P2-3 anti-lockout: stop dopo N checkPassword falliti consecutivi entro una
# finestra, per non far scattare il blocco PIN dell'ACCOUNT Chery (ogni PIN sbagliato
# incrementa gli errori lato loro, e quel blocco non si risolve da Home Assistant).
#
# Lo stato e il suo lock vivono ora dentro `PinLockout` (core/pin_lockout.py): l'unico
# modo di coniare è `attempt()`, che serializza guardia + POST + aggiornamento del
# contatore. Prima erano un dizionario e un lock separati, e bastava prendere il lock
# troppo tardi per riaprire la corsa P0-1.
_LOCKOUT = PinLockout(
    max_fail=int(os.environ.get("OMODA_PIN_FAIL_MAX", "2")),
    window_s=int(os.environ.get("OMODA_PIN_FAIL_WINDOW", "600")),
)
# Monitor diagnostico (diag.py): callback module-level impostato dal coordinator SOLO a
# monitor acceso — `core/` non conosce il coordinator e non deve importarlo. A `None`
# (default) il codice è dormiente e non costa nulla.
DIAG_HOOK = None
# Conii SOVRAPPOSTI: contatore d'ingresso tenuto FUORI dal lock dell'anti-lockout,
# altrimenti vedrebbe sempre 1 (il lock serializza). Se all'ingresso risulta >1, un
# secondo thread sta aspettando il lock proprio ora: è la corsa P0-1 vista dal vivo.
_MINT_INFLIGHT = {"n": 0}
_MINT_INFLIGHT_LOCK = threading.Lock()
# P1-2 — classificazione di checkPassword PER CODICE (prima: «tutto ciò che non dà un taskId
# = PIN errato», che è falso e fa due danni: propone il rimedio sbagliato all'utente e conta
# verso l'anti-lockout un errore che col PIN non c'entra nulla).
#
#   _SESSION_CODES → token/sessione morti: rimedio = riautenticazione (OTP), reason="reauth"
#   _CONFIG_CODES  → permessi veicolo o richiesta malformata (client/parametri): NON è il PIN,
#                    non esiste un rimedio automatico → reason="config", solo avviso
#   tutto il resto  → resta sul ramo PIN (default CONSERVATIVO voluto: A00285/A00282 e i codici
#                    ancora sconosciuti sono, per quanto osservato, davvero PIN errato)
#
# Nessuno dei due insiemi sopra conta verso il blocco né apre il Repair «PIN comandi errato».
_SESSION_CODES = {"A00000"}
_CONFIG_CODES = {
    "A00374", "A00554",                      # permessi/autorizzazione sul veicolo
    "A00567", "A00604", "A00643", "A00757",  # costruzione richiesta / clientType / taskId
}


def reset_pin_lockout() -> None:
    """Azzera il contatore anti-lockout dei PIN errati.

    Lo stato vive nel processo, non nel config entry: un semplice reload dell'entry
    (es. dopo aver corretto il PIN) NON lo azzera, quindi senza questa chiamata i
    comandi resterebbero bloccati fino allo scadere della finestra o a un riavvio di
    HA. Va invocata a ogni riconfigurazione del PIN (config flow / Repair) e dal
    `_bind_core` del coordinator quando rileva che il PIN è cambiato."""
    _LOCKOUT.reset()


def _mint_taskid(tuid):
    """Conia un taskId. A monitor spento è un passacarte diretto a `_mint_taskid_impl`.

    A monitor acceso osserva DUE cose che dal log non si vedono: i conii concorrenti
    (`pin_fail_concurrent`, la corsa che avvicina il lockout dell'account) e l'esito reale
    di checkPassword con il codice GREZZO del backend — l'unico modo per distinguere un
    PIN davvero errato da un rifiuto per permessi/parametri. Il PIN non viene mai
    registrato, in nessuna forma."""
    if DIAG_HOOK is None:
        return _mint_taskid_impl(tuid)
    with _MINT_INFLIGHT_LOCK:
        _MINT_INFLIGHT["n"] += 1
        inflight = _MINT_INFLIGHT["n"]
    if inflight > 1:
        DIAG_HOOK("pin_fail_concurrent", inflight=inflight)
    try:
        tid = _mint_taskid_impl(tuid)
        DIAG_HOOK("pin_event", outcome="ok", pin_fail_n=_LOCKOUT.tentativi_falliti)
        return tid
    except CommandError as err:
        # "fail" = il backend ha risposto e ha rifiutato; "empty" = PIN non configurato;
        # "blocked" = anti-lockout scattato. Gli ultimi due NON hanno interrogato il
        # backend: distinguerli conta, perché solo "fail" avvicina il lockout dell'account.
        # Si classifica sul marcatore nel messaggio, non sulla presenza del codice: un
        # rifiuto può arrivare anche senza codice, e finirebbe scambiato per un blocco.
        code = getattr(err, "code", None)
        if "checkPassword" in str(err):
            outcome = "fail"
        elif not (PIN or "").strip():
            outcome = "empty"
        else:
            outcome = "blocked"
        DIAG_HOOK("pin_event", outcome=outcome, reason=getattr(err, "reason", None), cp_code=code,
                  pin_fail_n=_LOCKOUT.tentativi_falliti,
                  pin_fail_max=_LOCKOUT.max_fail)
        raise
    except Exception as err:  # noqa: BLE001 — il monitor osserva, non altera il flusso
        DIAG_HOOK("pin_event", outcome="error", err_type=type(err).__name__)
        raise
    finally:
        with _MINT_INFLIGHT_LOCK:
            _MINT_INFLIGHT["n"] -= 1


def _mint_taskid_impl(tuid):
    """Conia un taskId con la catena BFF dell'app (queryList→setVecDefault→checkPassword).
       FIX S26 (2026-06-20): scene=0 (NON 2) → il taskId coniato è benedetto da tspconsole
       (airControl A00079). scene=2 dava A00089; scene=1 A00089; scene>=3 A00546. Obiettivo #1 RISOLTO.

       H6: rifiuta il conio se il PIN è vuoto (NON chiama checkPassword a vuoto) e si
       auto-blocca dopo troppi PIN errati consecutivi per evitare il lockout account.

       Su fallimento solleva SEMPRE CommandError con `reason` ("pin" o "reauth") così il
       coordinator può instradare il rimedio giusto (riconfig PIN vs riautenticazione)."""
    # PIN mancante: si fallisce PRIMA di entrare nell'anti-lockout. Un PIN non configurato
    # non è un tentativo errato — non deve consumare la soglia né toccare il backend.
    if not (PIN or "").strip():
        raise CommandError(
            "PIN comandi non configurato — impostalo nelle impostazioni dell'integrazione",
            reason="pin")

    # P2-3: `attempt()` prende il lock, applica la guardia e lo tiene per tutta la chiamata
    # di rete. È l'unico modo di coniare: la corsa P0-1 non è più esprimibile.
    try:
        with _LOCKOUT.attempt() as tentativo:
            return _checkpassword(tuid, tentativo)
    except PinLockedError as bloccato:
        raise CommandError(
            f"PIN comandi bloccato temporaneamente ({bloccato.tentativi} tentativi errati) — "
            "riconfigura il PIN nelle impostazioni dell'integrazione, poi riprova",
            reason="pin") from None


def _checkpassword(tuid, tentativo):
    """Catena BFF vera e propria. Gira col lock dell'anti-lockout già preso; dichiara
    l'esito su `tentativo` SOLO quando è davvero attribuibile al PIN."""
    import requests
    access = wake._access_token()
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}

    def bff(path, body):
        H = A.headers_post(path, extra=extra)
        r = requests.post(A.BFF + path, data=json.dumps(body), headers=H, timeout=25)
        try:
            j = r.json()
        except Exception:
            return {"_raw": r.text[:200]}
        # MED: il BFF può restituire un top-level non-dict (stringa) → normalizza a {}
        return j if isinstance(j, dict) else {}

    bff("/tsp/v1/app/vmc/queryList", {})
    bff("/tsp/v1/app/vmc/setVecDefault", {"vin": VIN})
    plain = hashlib.md5(PIN.encode()).hexdigest()
    password = A.sm4_code(plain, "padRight32")
    j = bff("/tsp/v1/app/cpm/checkPassword",
            {"vin": VIN, "tUserId": str(tuid), "channelId": A.CHANNEL_ID,
             "password": password, "needDecode": 0, "scene": 0, "type": 0})
    data = j.get("data") if isinstance(j.get("data"), dict) else {}
    tid = data.get("taskId") or j.get("taskId")
    if tid:
        tentativo.riuscito()      # il PIN è corretto → la soglia riparte da zero
        return tid

    # nessun taskId: distinguo la CAUSA per instradare il rimedio giusto.
    code = j.get("code")
    # DIAGNOSTICA (2026-07-06): il codice/messaggio GREZZO di checkPassword è l'UNICO modo per
    # sapere se è davvero un PIN errato o un'altra causa (permessi veicolo, parametri scene/
    # channelId, backend). Finora NON veniva loggato → dal log l'anti-lockout diceva solo "PIN
    # errati", che è la nostra INFERENZA. Ora logghiamo code + message reali (campi non sensibili).
    cp_msg = str(j.get("message") or j.get("msg") or "").strip()
    detail = f"code={code}" + (f" '{cp_msg[:100]}'" if cp_msg else "")
    _LOGGER.warning("[taskId] checkPassword NON ha restituito un taskId → %s "
                    "(risposta backend grezza; se non è un PIN errato la causa è qui)", detail)

    # NB: nei due rami qui sotto il tentativo resta NON dichiarato di proposito → non
    # conta verso il blocco. Non è il PIN, e contarlo avvicinerebbe il blocco
    # dell'account reale per una causa che col PIN non c'entra nulla (P1-2).
    if str(code) in _SESSION_CODES:
        # sessione/token (A00000): rimedio = riautenticazione, non riconfigurare il PIN.
        raise CommandError(
            f"Sessione scaduta [checkPassword {detail}] — riautentica dall'avviso di "
            "Home Assistant (nuovo codice OTP)",
            code=str(code), reason="reauth")
    if str(code) in _CONFIG_CODES:
        # permessi veicolo o richiesta rifiutata per come è costruita: il PIN può essere
        # perfettamente corretto → nessun Repair PIN (manderebbe a cambiare un PIN giusto).
        raise CommandError(
            f"Comando rifiutato dal backend [checkPassword {detail}] — non è il PIN: "
            "l'account non ha il permesso su questa auto oppure la richiesta è stata "
            "respinta. Riprova più tardi; se persiste servono i log.",
            code=str(code), reason="config")

    # ogni altro esito senza taskId = molto probabilmente PIN comandi errato → conta verso
    # il blocco e chiedi la riconfig-PIN (default conservativo voluto). Il `detail` col
    # codice reale resta nel messaggio e nel log per poterlo confermare.
    tentativo.fallito()
    raise CommandError(
        f"PIN comandi rifiutato dal backend [checkPassword {detail}] — riconfiguralo nelle "
        "impostazioni dell'integrazione",
        code=str(code) if code else None, reason="pin")


# Cache in memoria del taskId. Coniarlo significa fare tutto il giro di checkPassword (PIN):
# è la parte LENTA di ogni comando. Il taskId però resta valido per un po' → lo riusiamo e lo
# riconiamo solo quando l'auto lo rifiuta (TASKID_INVALID) o scade il TTL. Così la maggior parte
# dei comandi diventa una sola POST firmata invece di PIN + POST.
_TASKID_TTL = int(os.environ.get("OMODA_TASKID_TTL", "600"))   # riuso fino a ~10 min
_TASKID_CACHE = {"tid": None, "ts": 0.0}

# Codici con cui l'auto dice "questo taskId non va bene" → si riconia e si riprova una volta.
TASKID_INVALID = frozenset({"A00089", "A00546", "A00567"})


def invalidate_taskid():
    """Butta il taskId in cache (l'auto lo ha rifiutato come non valido/scaduto)."""
    _TASKID_CACHE["tid"] = None
    _TASKID_CACHE["ts"] = 0.0


def get_taskid(tuid, emit=lambda m: None, force_mint=False):
    """Sorgente taskId, in ordine: env TASKID → file piggyback → cache → checkPassword coniato.
    `force_mint=True` salta env/file/cache e ne conia uno nuovo (usato al retry dopo un rifiuto:
    ripescare la stessa sorgente rifiutata darebbe di nuovo lo stesso errore)."""
    if not force_mint:
        t = os.environ.get("TASKID")
        if t:
            return t.strip(), "env"
        try:
            if os.path.exists(TASKID_FILE):
                with open(TASKID_FILE) as fh:
                    v = fh.read().strip()
                if v:
                    return v, "file"
        except OSError:
            pass
        if _TASKID_CACHE["tid"] and (time.time() - _TASKID_CACHE["ts"]) < _TASKID_TTL:
            return _TASKID_CACHE["tid"], "cache"
    if MINT_TASKID:
        emit("conio taskId (checkPassword)…")
        try:
            tid = _mint_taskid(tuid)
        except CommandError as e:
            # PIN errato / anti-lockout / sessione: pubblica il dettaglio e PROPAGA (non più
            # inghiottito) → send() lo lascia salire col suo `reason` per il routing del rimedio.
            emit(str(e))
            raise
        except Exception as e:  # noqa: BLE001 — errore imprevisto del conio → PIN generico
            emit(f"checkPassword fallito: {e}")
            raise CommandError(
                "PIN comandi non verificabile — riconfiguralo nelle impostazioni "
                f"dell'integrazione ({e})", reason="pin") from e
        if tid:
            _TASKID_CACHE["tid"] = tid
            _TASKID_CACHE["ts"] = time.time()
            return tid, "checkPassword"
    return None, "none"


def send(cmd_key, emit=lambda m: None, params=None):
    """Invia un comando. emit(str) riceve i passaggi (per pubblicarli su HA).
       `params` (opzionale) = override/aggiunte al body del catalogo PRIMA dei campi
       comuni → permette i comandi parametrici (clima: temperature/times; ricarica
       immediata: controlType; ricarica programmata: mainSwitch + chargeAppointPlans).
       I campi di sistema (clientType/seq/taskId/vin) restano sempre quelli coniati qui.
       Ritorna una stringa-esito leggibile."""
    c = CMD_MAP.get(cmd_key)
    if not c:
        emit(f"comando sconosciuto: {cmd_key}")
        raise CommandError(f"Comando sconosciuto: {cmd_key}")

    token, tuid = wake._bff_login()
    if not token:
        emit("login fallito (token scaduto? rifare OTP ad app chiusa)")
        raise CommandError(
            "Sessione scaduta — riautentica dall'avviso di Home Assistant (nuovo codice OTP)",
            reason="reauth")

    # path esplicito (es. antifurto su /act/theftAlarm/setSwitch) oppure il classico
    # /asc/vehicleControl/<endpoint> per i comandi veicolo standard.
    url = TSP_HOST + (c.get("path") or ("/asc/vehicleControl/" + c["endpoint"]))

    # Tentativo 1 col taskId riusato (veloce). Se l'auto lo rifiuta come non valido/scaduto,
    # lo si riconia (checkPassword) e si riprova UNA volta sola.
    for attempt in (1, 2):
        # get_taskid propaga CommandError (PIN/anti-lockout/sessione) col suo `reason`.
        taskid, src = get_taskid(tuid, emit, force_mint=(attempt == 2))
        if not taskid:
            # P1-2 (#30): nessun taskId MA nessuna eccezione = il conio è DISATTIVATO
            # (OMODA_MINT_TASKID=0) e non c'era un taskId né in env né su file. Il PIN non
            # c'entra: dire «PIN errato» mandava l'utente a riconfigurare un PIN sano.
            emit("nessun taskId disponibile (conio disattivato)")
            raise CommandError(
                "Conio del taskId disattivato (OMODA_MINT_TASKID=0) e nessun taskId "
                "disponibile: i comandi non possono partire. Riattiva il conio automatico "
                "per usare i pulsanti.",
                reason="config")

        ts = int(time.time() * 1000)
        body = dict(c["body"])
        if params:
            body.update(params)    # override parametrico (temperatura/durata/controlType/piano)
        body.update({"clientType": "1", "seq": f"{VIN}-{ts}", "taskId": taskid, "vin": VIN})
        m = tsp_sign.sign_body(body, ts)
        payload = json.dumps(m, separators=(",", ":"), ensure_ascii=False).encode()
        headers = {"Authorization": token, "timestamp": str(ts),
                   "Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}
        emit(f"invio {c['name']} (taskId:{src})…")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status = e.code
        except Exception as e:
            emit(f"errore rete: {e}")
            raise CommandError(f"Errore di rete durante l'invio del comando: {e}")

        code = None
        try:
            code = json.loads(raw).get("code")
        except Exception:
            pass

        # taskId rifiutato al primo giro → riconia e ripeti (l'utente non vede un falso errore).
        if attempt == 1 and str(code) in TASKID_INVALID and MINT_TASKID:
            invalidate_taskid()
            emit("taskId non più valido → lo rinnovo e riprovo…")
            continue
        break

    meaning = CODE_MEANING.get(code, raw[:120])
    out = f"{c['name']}: HTTP {status} {code or ''} — {meaning}"
    emit(out)
    # esito reale dal `code`: un codice di fallimento noto = comando NON eseguito → solleva
    # CommandError (l'emit ha già pubblicato il dettaglio su «Esito comando»). I codici
    # sconosciuti restano "non bloccanti" (return) per prudenza: non inventiamo un fallimento.
    if str(code) in FAILURE_CODES:
        # A00000 = token scaduto → reauth (nuovo OTP); gli altri rifiuti non hanno rimedio
        # automatico (auto occupata/non consentita/a riposo) → solo avviso.
        reason = "reauth" if str(code) == "A00000" else None
        raise CommandError(out, code=str(code), reason=reason)
    return out


def query_theft_switch():
    """Legge lo stato dell'antifurto (READ-ONLY, /act/theftAlarm/querySwitch).
       Ritorna 1/0 (int) oppure None se non disponibile. NON usa taskId né attua nulla:
       la risposta mette il valore sotto `body.theftAlarmSwitch`."""
    token, _tuid = wake._bff_login()
    if not token:
        return None
    try:
        _status, j = wake._signed_post(token, "/act/theftAlarm/querySwitch", {"vin": VIN})
    except Exception:
        return None
    if isinstance(j, dict):
        body = j.get("body") if isinstance(j.get("body"), dict) else {}
        v = body.get("theftAlarmSwitch")
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


if __name__ == "__main__":
    # Diagnostica: elenca i comandi (NON invia nulla).
    for k, v in COMMANDS:
        print(f"{k:22s} {(v.get('path') or v.get('endpoint','')):28s} {v['body']}")
