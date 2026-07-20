"""Fixture ANONIMIZZATE del protocollo (P2-8/C3) — golden file versionati.

La conoscenza del protocollo Omoda viveva sparsa in note di sessione: qui diventa
materiale verificabile e diff-abile quando il backend cambia. Due famiglie:

  * **codici `A00xxx`** = risposte del backend tspconsole/BFF, con il significato e
    soprattutto il RIMEDIO atteso (`reason`). È la tabella su cui P2-5 costruirà il
    routing unico: i test qui sotto la bloccano PRIMA del refactor, così il refactor
    non può cambiare in silenzio come viene classificato un codice.
  * **envelope MQTT** `5A02` (telemetria), `1301` (posizione), `110x` (conferma comando),
    ricostruiti 1:1 nella forma reale ma con valori sintetici.

⚠️ Nessun dato reale. VIN/email/token/taskId hanno il FORMATO dei veri (il codice li
tratta per forma: lunghezza, prefisso, tipo) ma non appartengono a nessun account. Sono
scelti anche per non far scattare `check_secrets.sh` — vedi il marcatore sul VIN.
"""
from __future__ import annotations

import json

# ───────────────────────── identità sintetiche ─────────────────────────
VIN = "LZZAAAAAA1B2C3D4E"          # VIN_PLACEHOLDER: sintetico, non è un VIN reale
EMAIL = "mario.rossi@example.com"
PIN = "4917"
TUSERID = "100000000000000001"
ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlX2ZpbnRh"
USER_TOKEN = "ut_0123456789abcdef0123456789abcdef"
TASKID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
TSP_HOST = "https://tspconsole.example.invalid"
BFF = "https://bff.example.invalid/api"


def token_json() -> str:
    """token.json nella forma reale ({data:{...}}), con valori finti."""
    return json.dumps({"data": {"access_token": ACCESS_TOKEN,
                                "refresh_token": "rt_finto_0123456789abcdef",
                                "expires_in": 43200}})


# ───────────────────────── codici backend → rimedio atteso ─────────────────────────
# `reason` è ciò che il coordinator usa per instradare il rimedio all'utente:
#   "pin"    → Repair «PIN comandi errato» (riconfigura il PIN)
#   "reauth" → riautenticazione nativa HA (nuovo OTP)
#   "config" → nessun rimedio automatico, solo avviso (permessi/richiesta malformata)
#   None     → rifiuto dell'auto (occupata / non consentito / a riposo): solo avviso
#
# `counts_lockout` = se quel codice deve incrementare l'anti-lockout del PIN. È il campo
# che più conta: un `True` di troppo qui significa avvicinare il blocco dell'ACCOUNT REALE
# per un errore che col PIN non c'entra nulla (è il bug P1-2, chiuso in v1.5.27).
CHECKPASSWORD_CODES = {
    # — sessione morta: serve un OTP nuovo, il PIN è irrilevante —
    "A00000": {"reason": "reauth", "counts_lockout": False,
               "note": "token/sessione scaduti"},
    # — non è il PIN: permessi veicolo o richiesta costruita male —
    "A00374": {"reason": "config", "counts_lockout": False, "note": "permessi veicolo"},
    "A00554": {"reason": "config", "counts_lockout": False, "note": "autorizzazione veicolo"},
    "A00567": {"reason": "config", "counts_lockout": False, "note": "taskId non valido"},
    "A00604": {"reason": "config", "counts_lockout": False, "note": "clientType mancante/errato"},
    "A00643": {"reason": "config", "counts_lockout": False, "note": "taskId assente"},
    "A00757": {"reason": "config", "counts_lockout": False, "note": "richiesta malformata"},
    # — davvero il PIN (default conservativo voluto: anche i codici ignoti finiscono qui) —
    "A00285": {"reason": "pin", "counts_lockout": True, "note": "password/PIN errato"},
    "A00282": {"reason": "pin", "counts_lockout": True, "note": "password/PIN errato"},
    "A99999": {"reason": "pin", "counts_lockout": True, "note": "codice SCONOSCIUTO → ramo PIN"},
}

# Esito dell'invio comando (`commands.send`): il backend risponde SEMPRE HTTP 200 e
# l'esito vero sta nel `code` del body.
COMMAND_CODES = {
    "000000": {"ok": True,  "reason": None, "retryable": False, "note": "accettato"},
    "A00079": {"ok": True,  "reason": None, "retryable": False, "note": "accettato dall'auto"},
    "A00082": {"ok": False, "reason": None, "retryable": True,
               "note": "veicolo OCCUPATO (un comando alla volta) → ritentabile"},
    "A00084": {"ok": False, "reason": None, "retryable": False, "note": "comando non consentito"},
    "A00089": {"ok": False, "reason": None, "retryable": False, "note": "taskId non valido"},
    "A00546": {"ok": False, "reason": None, "retryable": False, "note": "taskId non valido"},
    "A00567": {"ok": False, "reason": None, "retryable": False, "note": "taskId non valido"},
    "A00000": {"ok": False, "reason": "reauth", "retryable": False, "note": "token scaduto"},
    "A07312": {"ok": False, "reason": None, "retryable": False, "note": "rate-limit sveglia"},
    "A07900": {"ok": False, "reason": None, "retryable": False, "note": "auto a riposo"},
}

# taskId rifiutato → si riconia e si riprova UNA volta (poi si arrende)
TASKID_INVALID_CODES = ("A00089", "A00546", "A00567")


# ───────────────────────── envelope MQTT ─────────────────────────
def envelope(service_type: str, data: dict) -> dict:
    """Involucro reale dei push dell'auto: {content:{serviceType, data:{...}}}."""
    return {"content": {"serviceType": service_type, "vin": VIN, "data": data}}


def telemetry_5a02(**overrides) -> dict:
    """Telemetria di stato 5A02 — il push più frequente (porte/clima/sedili/ricarica).

    I valori sono STRINGHE, come li manda l'auto: il mapping in HA li normalizza. Il
    campo `time` e i meta di conferma non devono finire fra i `fields` (vedi test)."""
    data = {
        "frontLeftDoor": "0", "frontRightDoor": "0",
        "backLeftDoor": "0", "backRightDoor": "0",
        "trunkDoor": "0", "hood": "0",
        "doorLock": "0",                 # 0 = Bloccata (verificato dal vivo 2026-06-17)
        "frontLeftWindowState": "0", "frontRightWindowState": "0",
        "backLeftWindowState": "0", "backRightWindowState": "0",
        "sunroofState": "0", "frontHVACState": "0",
        "chargeGunState": "0", "engineState": "0",
        "dSeatHeatingState": "0", "pSeatHeatingState": "0",
        "steerWheelHeating": "0", "rWinHeatingState": "0",
        # flag di UNITÀ, non valori: valgono sempre "1" e NON vanno mappati a sensori
        "rangeUnit": "1", "averageFuelUnit": "1", "tirePressureUnit": "1",
        "time": "1721390000000",
    }
    data.update({k: str(v) for k, v in overrides.items()})
    return envelope("5A02", data)


def position_1301(lat: float = 45.070312, lon: float = 7.686856) -> dict:
    """Push posizione: arriva SOLO in risposta al comando `vehicleLocation`."""
    return envelope("1301", {"lat": str(lat), "lon": str(lon),
                             "direction": "180", "gpsTime": "1721390000000"})


def cmd_confirm(service_type: str = "1105", result: str = "1",
                reason: list | None = None) -> dict:
    """Conferma comando dall'AUTO (diversa dall'«accettato» del backend).

    `result` 1/2 = eseguito, 5 = in corso (asincrono); `reason` valorizzato = fallito."""
    data = {"result": result, "resultTime": "1721390001000", "seq": f"{VIN}-1721390000"}
    if reason is not None:
        data["reason"] = reason
    if result == "5":
        data["hasAsy"] = "1"
    # una conferma porta ANCHE campi di stato reali: devono entrare nei fields
    data["doorLock"] = "1"
    return envelope(service_type, data)


# risposta realtime (/asr/manager/realtime) ad auto FERMA: segnaposto, non dati veri.
REALTIME_PLACEHOLDER = {
    "code": "000000",
    "body": {"dumpEnergy": "0", "totalVoltage": "0", "totalCurrent": "-1000",
             "averageEnergyConsumption": "-100", "hVoltageState": "0",
             "engineState": "0", "odometer": "12345", "resultTime": "1721390000000"},
}

# realtime con l'alta tensione ACCESA: qui i valori sono reali (marcia/ricarica)
REALTIME_LIVE = {
    "code": "000000",
    "body": {"dumpEnergy": "72", "totalVoltage": "384", "totalCurrent": "35",
             "averageEnergyConsumption": "17", "hVoltageState": "1",
             "engineState": "1", "odometer": "12420", "vehicleSpeed": "38",
             "lat": "45.070312", "lon": "7.686856", "resultTime": "1721390600000"},
}

# auto a riposo: il cloud non ha un frame da restituire
REALTIME_ASLEEP = {"code": "A07900"}
