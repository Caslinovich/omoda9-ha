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
import sys
import json
import time
import hashlib
import importlib
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import wake
import tsp_sign
import omoda_auth as A
importlib.reload(tsp_sign)

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
    ("clima_on",  {"endpoint": "airControl",
                   "body": {"airControlType": "1", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Clima ON (21°, 15min)", "icon": "mdi:air-conditioner", "group": "Clima"}),
    ("clima_off", {"endpoint": "airControl",
                   "body": {"airControlType": "0", "airType": "1", "temperature": "21.0", "times": "15"},
                   "name": "Clima OFF", "icon": "mdi:air-conditioner", "group": "Clima"}),
    ("defrost_parabrezza", {"endpoint": "frontWindshieldControl",
                   "body": {"frontWindshieldHeat": "1", "times": "15"},
                   "name": "Sbrina parabrezza", "icon": "mdi:car-defrost-front", "group": "Clima"}),
    ("defrost_lunotto", {"endpoint": "backDefrostingControl",
                   "body": {"backDefrosting": "1", "times": "15"},
                   "name": "Sbrina lunotto", "icon": "mdi:car-defrost-rear", "group": "Clima"}),
    ("volante_caldo", {"endpoint": "steeringWheelControl",
                   "body": {"controlType": "1"},
                   "name": "Volante riscaldato", "icon": "mdi:steering", "group": "Clima"}),
    ("sedile_guida_caldo", {"endpoint": "seatControl",
                   "body": {"mSeatHeating": "3", "times": "15"},
                   "name": "Sedile guida riscaldato", "icon": "mdi:car-seat-heater", "group": "Clima"}),
    ("sedile_guida_aria", {"endpoint": "seatControl",
                   "body": {"mSeatAiry": "3", "times": "15"},
                   "name": "Sedile guida ventilato", "icon": "mdi:car-seat-cooler", "group": "Clima"}),

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

    # — Altro —
    ("trova_auto", {"endpoint": "findCar", "body": {},
                   "name": "Trova auto (lampeggio)", "icon": "mdi:car-search", "group": "Altro"}),
    # Richiesta posizione GPS: NON attua nulla; l'auto risponde con un push MQTT serviceType 1301
    # (lat/lon) che il bridge cabla nel device_tracker. È il metodo dell'app per la posizione a riposo.
    ("localizza", {"endpoint": "vehicleLocation", "body": {},
                   "name": "Localizza auto (GPS)", "icon": "mdi:crosshairs-gps", "group": "Altro"}),
]
CMD_MAP = {k: v for k, v in COMMANDS}

# Codici risposta tspconsole noti → testo leggibile
CODE_MEANING = {
    "A00079": "comando accettato ✅",
    "000000": "ok ✅",
    "A00089": "taskId non valido ❌ (manca un taskId benedetto: vedi obiettivo #1)",
    "A07900": "firma rifiutata ❌",
    "A00000": "token scaduto/non valido ❌",
    "A00567": "parametri checkPassword incompleti ❌",
}


def _access_token():
    with open(wake._token_path()) as fh:
        tok = json.load(fh)
    return tok.get("data", tok).get("access_token") if isinstance(tok.get("data", tok), dict) else tok.get("access_token")


def _mint_taskid(tuid):
    """Conia un taskId con la catena BFF dell'app (queryList→setVecDefault→checkPassword).
       FIX S26 (2026-06-20): scene=0 (NON 2) → il taskId coniato è benedetto da tspconsole
       (airControl A00079). scene=2 dava A00089; scene=1 A00089; scene>=3 A00546. Obiettivo #1 RISOLTO."""
    import requests
    access = _access_token()
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}

    def bff(path, body):
        H = A.headers_post(path, extra=extra)
        r = requests.post(A.BFF + path, data=json.dumps(body), headers=H, timeout=25)
        try:
            return r.json()
        except Exception:
            return {"_raw": r.text[:200]}

    bff("/tsp/v1/app/vmc/queryList", {})
    bff("/tsp/v1/app/vmc/setVecDefault", {"vin": VIN})
    plain = hashlib.md5(PIN.encode()).hexdigest()
    password = A.sm4_code(plain, "padRight32")
    j = bff("/tsp/v1/app/cpm/checkPassword",
            {"vin": VIN, "tUserId": str(tuid), "channelId": A.CHANNEL_ID,
             "password": password, "needDecode": 0, "scene": 0, "type": 0})
    data = j.get("data") if isinstance(j.get("data"), dict) else {}
    return data.get("taskId") or j.get("taskId")


def get_taskid(tuid, emit=lambda m: None):
    """Sorgente taskId, in ordine: env TASKID → file piggyback → checkPassword auto-coniato."""
    t = os.environ.get("TASKID")
    if t:
        return t.strip(), "env"
    try:
        if os.path.exists(TASKID_FILE):
            v = open(TASKID_FILE).read().strip()
            if v:
                return v, "file"
    except Exception:
        pass
    if MINT_TASKID:
        emit("conio taskId (checkPassword)…")
        try:
            tid = _mint_taskid(tuid)
            if tid:
                return tid, "checkPassword"
        except Exception as e:
            emit(f"checkPassword fallito: {e}")
    return None, "none"


def send(cmd_key, emit=lambda m: None):
    """Invia un comando. emit(str) riceve i passaggi (per pubblicarli su HA).
       Ritorna una stringa-esito leggibile."""
    c = CMD_MAP.get(cmd_key)
    if not c:
        emit(f"comando sconosciuto: {cmd_key}")
        return f"sconosciuto: {cmd_key}"

    token, tuid = wake._bff_login()
    if not token:
        emit("login fallito (token scaduto? rifare OTP ad app chiusa)")
        return "login_failed"

    taskid, src = get_taskid(tuid, emit)
    if not taskid:
        emit("nessun taskId disponibile")
        return "no_taskid"

    ts = int(time.time() * 1000)
    body = dict(c["body"])
    body.update({"clientType": "1", "seq": f"{VIN}-{ts}", "taskId": taskid, "vin": VIN})
    m = tsp_sign.sign_body(body, ts)
    payload = json.dumps(m, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {"Authorization": token, "timestamp": str(ts),
               "Content-Type": "application/json; charset=utf-8", "User-Agent": "okhttp/4.9.2"}
    url = TSP_HOST + "/asc/vehicleControl/" + c["endpoint"]
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
        return f"net_error: {e}"

    code = None
    try:
        code = json.loads(raw).get("code")
    except Exception:
        pass
    meaning = CODE_MEANING.get(code, raw[:120])
    out = f"{c['name']}: HTTP {status} {code or ''} — {meaning}"
    emit(out)
    return out


if __name__ == "__main__":
    # Diagnostica: elenca i comandi (NON invia nulla).
    for k, v in COMMANDS:
        print(f"{k:22s} {v['endpoint']:24s} {v['body']}")
