#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
provision.py — Catena di PROVISIONING del comando veicolo Omoda 9 (SESSIONE 16).

SCOPERTA (workflow 5-agenti, S16 — prove file:riga in SESSIONE16_REPORT.md):
  I comandi `/asc/vehicleControl/*` NON vogliono lo `userToken` del BFF (è quello
  che usiamo noi → A07900 universale), ma un **car_token per-veicolo**.
  La catena reale dell'app (rus_car_control_provider.dart:6511-6567) è:

      getTuserId → loginTSP (= car_token) → queryList → setVecDefault(vin)
      → checkPassword(scene=2 → taskId) → comando  (Authorization = car_token)

  - `loginCheck` NON è in questa catena (è il QR-login sull'infotainment, scartato).
  - L'autorizzazione veicolo non è un boolean: è l'int `authorizeType` del bean
    RusCarAuthorize (==2 proprietà → controlCarList; ==0 delegato →
    authorizedControlCarList). Il VIN deve comparire in una delle due liste.
  - Il car_token lato Dart = CurrentVehicle.token, popolato da getTspToken()/
    loginTSP (impl NATIVA, nop nel DEX). DA-VERIFICARE se è anche un campo della
    risposta `queryList` del BFF: è ESATTAMENTE ciò che la FASE A qui sotto misura.

──────────────────────────────────────────────────────────────────────────────
DUE FASI NETTAMENTE SEPARATE:

  FASE A — `diagnose()` : DIAGNOSTICA, SOLA LETTURA, **NON tocca l'auto**.
      Chiama solo il BFF (legend-oj): login → getTuserId → queryList.
      Per il nostro VIN stampa: lista di appartenenza, authorizeType, e CERCA un
      eventuale campo token per-veicolo (car_token) nella risposta.
      NIENTE `/asc/vehicleControl/*`, NIENTE smsAwaken, NIENTE checkPassword.
      È il test che discrimina le ipotesi A/B/C senza alcun effetto sulla macchina.

  FASE B — `run_command()` : ATTIVA. Esegue setVecDefault(vin) → checkPassword(PIN)
      → comando, usando come Authorization il **car_token** (non lo userToken).
      Da lanciare SOLO con OK esplicito e ad auto sveglia. checkPassword col PIN
      GIUSTO è rieseguibile; un PIN SBAGLIATO rischia il lockout → mai indovinare.

REGOLE: questo modulo NON viene eseguito all'import. `__main__` di default fa la
sola FASE A (read-only). La FASE B parte solo con argomento esplicito `command`.

Uso strettamente personale (auto/account di Rino). NON pubblicare token/PIN/cert.
"""
import os, sys, json, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))

import requests

# P2-2: import relativi di pacchetto (prima: nomi nudi + `sys.path.insert(HERE)`).
from . import omoda_auth as A
from . import tsp_sign as S
from . import wake as W   # riusa _access_token / _bff_login / _signed_post / _code_of (già verificati)
from . import codes

VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: vedi omoda9.env.example
PIN        = os.environ.get("PIN", os.environ.get("OMODA_PIN", ""))   # PIN di controllo (PER-ACCOUNT)
# PRIVACY: i record contengono VIN/identificativi account → log OPT-IN, spento di default.
# Si attiva solo valorizzando OMODA_PROV_LOG col path del file da scrivere.
PROV_LOG   = os.environ.get("OMODA_PROV_LOG", "")

# Endpoint BFF (legend-oj) della catena di provisioning — tutti POST, Bearer access_token + sign app.
BFF_GETTUSERID    = "/tsp/v1/app/auth/getTuserId"
BFF_QUERYLIST     = "/tsp/v1/app/vmc/queryList"
BFF_SETVECDEFAULT = "/tsp/v1/app/vmc/setVecDefault"
BFF_CHECKPASSWORD = "/tsp/v1/app/cpm/checkPassword"

# nomi-chiave candidati per il token per-veicolo dentro la risposta queryList (DA-VERIFICARE)
CAR_TOKEN_KEYS = ("token", "tspToken", "carToken", "accessToken", "vehicleToken", "controlToken")


# ───────────────────────── util ────────────────────────────────────────────────
def _log(rec: dict):
    if not PROV_LOG:
        return
    rec = {"ts": round(time.time(), 3),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()), **rec}
    try:
        os.makedirs(os.path.dirname(PROV_LOG), exist_ok=True)
        with open(PROV_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _redact(body: dict) -> dict:
    """Per i log/stampe: non mostrare il PIN cifrato né i token in chiaro."""
    out = {}
    for k, v in (body or {}).items():
        if k in ("password",) or k.lower().endswith("token"):
            out[k] = f"<{len(str(v))}ch>" if v else v
        else:
            out[k] = v
    return out


# ───────────────────────── chiamate BFF autenticate (patchabili nei test) ───────
def _bff_call(path: str, params: dict = None, method: str = "POST"):
    """POST/GET autenticato al BFF legend-oj: Bearer access_token + headerSignature app.

    È lo schema PROVATO (stage2_tsp.py / checkpw_oneshot.py): le route vmc/cpm/auth
    del BFF accettano l'access_token come Bearer. Ritorna (status_code, json)."""
    access = W._access_token()
    extra = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json; charset=UTF-8",
             "Accept": "application/json, text/plain, */*"}
    H = A.headers_post(path, extra=extra)
    url = A.BFF + path
    if method.upper() == "GET":
        r = requests.get(url, params=params or {}, headers=H, timeout=25)
    else:
        r = requests.post(url, data=json.dumps(params or {}), headers=H, timeout=25)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:400]}


def get_tuser_id(user_id: str = None):
    """getTuserId — ritorna (status, json). Query {channelId, userId} (user_id opzionale)."""
    q = {"channelId": A.CHANNEL_ID}
    if user_id:
        q["userId"] = str(user_id)
    return _bff_call(BFF_GETTUSERID, q, method="GET")


def query_list():
    """queryList — POST {} → lista veicoli (controlCarList / authorizedControlCarList)."""
    return _bff_call(BFF_QUERYLIST, {}, method="POST")


def set_vec_default(vin: str = None):
    """setVecDefault — POST {vin}. Bind del veicolo attivo. NON raggiunge il TBOX."""
    return _bff_call(BFF_SETVECDEFAULT, {"vin": vin or VIN}, method="POST")


def check_password(tuser_id: str, pin: str = None, vin: str = None, scene: int = 2):
    """checkPassword(scene=2) → (status, json, taskId). password = sm4(md5(pin)).

    Ricetta chiusa in S10/confermata S16: md5(pin) poi sm4RandomString (padRight32),
    needDecode=0, type=0, scene=2. PIN GIUSTO è rieseguibile (non incrementa errori)."""
    pin = pin or PIN
    plain = hashlib.md5(pin.encode("utf-8")).hexdigest()      # generateMd5(pin)
    password = A.sm4_code(plain, "padRight32")                # sm4RandomString(md5(pin))
    body = {"vin": vin or VIN, "tUserId": str(tuser_id), "channelId": A.CHANNEL_ID,
            "password": password, "needDecode": 0, "scene": scene, "type": 0}
    sc, j = _bff_call(BFF_CHECKPASSWORD, body, method="POST")
    data = j.get("data") if isinstance(j, dict) and isinstance(j.get("data"), dict) else {}
    task_id = data.get("taskId") or (j.get("taskId") if isinstance(j, dict) else None)
    return sc, j, task_id


def send_command(cmd: str, car_token: str, vin: str = None, tuser_id: str = None,
                 task_id: str = None, extra_body: dict = None):
    """Invia il comando a tspconsole-eu con Authorization = **car_token** (non userToken).

    Body base = {channelId, tUserId, vin} (+ taskId se presente) come da
    i18n_car_quest_model.dart:3190; `extra_body` per campi specifici del comando
    (es. switchStatus). Riusa wake._signed_post passando il car_token come token.
    Ritorna (status, json)."""
    body = {"vin": vin or VIN, "channelId": A.CHANNEL_ID}
    if tuser_id:
        body["tUserId"] = str(tuser_id)
    if task_id:
        body["taskId"] = task_id
    if extra_body:
        body.update(extra_body)
    path = cmd if cmd.startswith("/") else f"/asc/vehicleControl/{cmd}"
    return W._signed_post(car_token, path, body)


# ───────────────────────── estrazione veicolo dalla risposta queryList ──────────
def _iter_vehicles(qlist_json):
    """Restituisce [(list_name, item_dict)] per ogni veicolo nelle liste della risposta.

    Robusto a forme diverse: data.controlCarList / data.authorizedControlCarList, ma
    anche data come lista, o liste annidate. list_name = etichetta diagnostica."""
    out = []
    data = qlist_json.get("data") if isinstance(qlist_json, dict) else None
    named = {}
    if isinstance(data, dict):
        for key in ("controlCarList", "authorizedControlCarList", "carList", "list", "vehicles"):
            v = data.get(key)
            if isinstance(v, list):
                named[key] = v
        if not named:
            # data potrebbe essere già un singolo veicolo
            if any(k in data for k in ("vin", "VIN")):
                out.append(("data", data))
    elif isinstance(data, list):
        named["data"] = data
    for name, lst in named.items():
        for it in lst:
            if isinstance(it, dict):
                out.append((name, it))
    return out


def _vin_of(item: dict) -> str:
    for k in ("vin", "VIN", "Vin"):
        if item.get(k):
            return str(item[k])
    return ""


def _car_token_in(item: dict):
    """Cerca un campo token per-veicolo nel bean (chiave + valore), altrimenti (None, None)."""
    for k in CAR_TOKEN_KEYS:
        if item.get(k):
            return k, item[k]
    # ricerca case-insensitive su chiavi che contengono 'token'
    for k, v in item.items():
        if "token" in k.lower() and v:
            return k, v
    return None, None


def find_our_vehicle(qlist_json, vin: str = None):
    """→ dict {found, list_name, authorize_type, car_token_key, car_token, item} per il nostro VIN."""
    vin = vin or VIN
    for list_name, item in _iter_vehicles(qlist_json):
        if _vin_of(item) == vin:
            ck, cv = _car_token_in(item)
            return {"found": True, "list_name": list_name,
                    "authorize_type": item.get("authorizeType"),
                    "car_token_key": ck, "car_token": cv, "item": item}
    return {"found": False, "list_name": None, "authorize_type": None,
            "car_token_key": None, "car_token": None, "item": None}


# ───────────────────────── FASE A: diagnostica SOLA LETTURA ─────────────────────
def diagnose(publish):
    """FASE A — login → getTuserId → queryList. **Nessun comando, non tocca l'auto.**

    Discrimina le ipotesi del report S16:
      - VIN presente + car_token nella risposta → ipotesi B risolvibile (basta il bind).
      - VIN presente ma nessun car_token → ipotesi A (token da loginTSP nativo).
      - VIN assente / lista vuota → account non legato al veicolo (non aggirabile).
    Ritorna un dict riepilogativo. Mai solleva."""
    try:
        publish("🔎 Diagnostica veicolo (sola lettura, non tocca l'auto)…")
        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Sessione scaduta: rifai il login OTP (token.json).")
            return {"ok": False, "reason": "no_usertoken"}

        # getTuserId (informativo; tUserId arriva già dal login)
        sc_t, j_t = get_tuser_id()
        tuser = tu or (j_t.get("data") if isinstance(j_t, dict) else None)

        # queryList → liste veicoli
        sc_q, j_q = query_list()
        code_q = W._code_of(j_q)
        veh = find_our_vehicle(j_q, VIN)

        _log({"event": "diagnose", "getTuserId_http": sc_t, "queryList_http": sc_q,
              "queryList_code": code_q, "tUserId": tu, "vehicle": {
                  k: veh[k] for k in ("found", "list_name", "authorize_type",
                                      "car_token_key")},
              "car_token_present": bool(veh["car_token"]),
              "queryList_data": j_q.get("data") if isinstance(j_q, dict) else None})

        if not veh["found"]:
            publish(f"🟥 VIN {VIN} NON presente nelle liste (code={code_q}). "
                    "→ account non autorizzato al controllo: nessun software lo aggira.")
            return {"ok": True, "found": False, "queryList_code": code_q,
                    "hypothesis": "account_not_bound"}

        at = veh["authorize_type"]
        which = veh["list_name"]
        if veh["car_token"]:
            publish(f"🟩 VIN trovato in {which} (authorizeType={at}) e la risposta CONTIENE "
                    f"un token per-veicolo (campo '{veh['car_token_key']}') → ipotesi B: "
                    "basta il bind + usare quel car_token nel comando.")
            hyp = "B_cartoken_in_querylist"
        else:
            publish(f"🟨 VIN trovato in {which} (authorizeType={at}) ma NESSUN car_token "
                    "nella risposta → ipotesi A: il car_token nasce da loginTSP (nativo), "
                    "da replicare. Bind possibile, token da trovare.")
            hyp = "A_cartoken_from_logintsp"
        return {"ok": True, "found": True, "list_name": which, "authorize_type": at,
                "car_token_key": veh["car_token_key"], "has_car_token": bool(veh["car_token"]),
                "queryList_code": code_q, "tUserId": tu, "hypothesis": hyp}
    except Exception as e:
        publish(f"⚠️ Diagnostica errore: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}


# ───────────────────────── FASE B: catena attiva (gated) ────────────────────────
def run_command(publish, cmd: str = "remoteStart", pin: str = None,
                extra_body: dict = None, is_awake=None):
    """FASE B — setVecDefault(vin) → checkPassword(PIN, scene=2) → comando con car_token.

    ⚠️ ATTIVA: invia un comando reale all'auto. Da chiamare SOLO con OK esplicito e
    auto sveglia. Usa il car_token trovato in diagnose() (ipotesi B); se assente,
    NON inventa: si ferma e segnala che serve la pista loginTSP (ipotesi A).
    Ritorna un dict riepilogativo. Mai solleva."""
    try:
        if is_awake is not None and not is_awake():
            publish("⌛ Auto a riposo: il comando darebbe A07900. Sveglia prima (uso reale).")
            return {"ok": False, "reason": "asleep"}

        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Sessione scaduta: rifai il login OTP.")
            return {"ok": False, "reason": "no_usertoken"}

        # 1) diagnostica/queryList per ottenere il car_token (ipotesi B)
        sc_q, j_q = query_list()
        veh = find_our_vehicle(j_q, VIN)
        if not veh["found"]:
            publish(f"🟥 VIN non in lista (code={W._code_of(j_q)}): non autorizzato. Stop.")
            return {"ok": False, "reason": "vehicle_not_found"}
        car_token = veh["car_token"]
        if not car_token:
            publish("🟨 Nessun car_token nella queryList → serve loginTSP (ipotesi A), "
                    "impl nativa non ancora replicata. Stop prima di sparare comandi.")
            return {"ok": False, "reason": "no_car_token", "hypothesis": "A_cartoken_from_logintsp"}

        # 2) bind veicolo (NON tocca il TBOX)
        sc_s, j_s = set_vec_default(VIN)
        publish(f"🔗 setVecDefault → {W._code_of(j_s)}")

        # 3) checkPassword(scene=2) → taskId
        sc_p, j_p, task_id = check_password(tu, pin=pin, vin=VIN, scene=2)
        if not task_id:
            publish(f"🔐 checkPassword senza taskId (code={W._code_of(j_p)}): "
                    "PIN non accettato o token scaduto. Stop (no retry su PIN).")
            return {"ok": False, "reason": "no_taskid", "code": W._code_of(j_p)}
        publish("🔐 PIN ok, taskId ottenuto. Invio comando col car_token…")

        # 4) comando con Authorization = car_token
        sc_c, j_c = send_command(cmd, car_token, vin=VIN, tuser_id=tu,
                                 task_id=task_id, extra_body=extra_body)
        code_c = W._code_of(j_c)
        _log({"event": "command", "cmd": cmd, "car_token_key": veh["car_token_key"],
              "setVecDefault_code": W._code_of(j_s), "checkPassword_http": sc_p,
              "command_http": sc_c, "command_code": code_c})

        if str(code_c) == "A00079":
            publish(f"✅ Comando {cmd} ACCETTATO (A00079)! Esito via push MQTT.")
            return {"ok": True, "code": code_c, "cmd": cmd}
        if str(code_c) == "A07900":
            publish(f"🟧 Ancora A07900 col car_token → resta in piedi l'ipotesi C "
                    "(body cifrato SM4) o car_token errato.")
        else:
            publish(f"ℹ️ Comando {cmd}: code={code_c} ({codes.meaning(code_c)}).")
        return {"ok": True, "code": code_c, "cmd": cmd, "accepted": False}
    except Exception as e:
        publish(f"⚠️ run_command errore: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}


# ───────────────────────── self-test (NESSUNA chiamata di rete reale) ───────────
if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "selftest"

    if arg == "diagnose":
        # FASE A LIVE (read-only) — l'utente la lancia quando dà l'OK.
        pub = lambda t: print("  STATUS:", t)
        print(json.dumps(diagnose(pub), ensure_ascii=False, indent=2))
        sys.exit(0)

    if arg == "command":
        # FASE B LIVE (ATTIVA) — richiede env OMODA_CONFIRM=1 per evitare lanci accidentali.
        if os.environ.get("OMODA_CONFIRM") != "1":
            print("RIFIUTO: FASE B attiva. Rilancia con OMODA_CONFIRM=1 e ad auto sveglia.")
            sys.exit(2)
        cmd = sys.argv[2] if len(sys.argv) > 2 else "remoteStart"
        pub = lambda t: print("  STATUS:", t)
        print(json.dumps(run_command(pub, cmd=cmd), ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── default: self-test OFFLINE con mock (nessuna rete) ──
    pub = lambda t: print("  STATUS:", t)

    print("== TEST find_our_vehicle: car_token presente in controlCarList ==")
    mock_q = {"code": "000000", "data": {"controlCarList": [
        {"vin": "VIN_PLACEHOLDER", "authorizeType": 2, "token": "CARTOK123", "defaultFlag": 1},
        {"vin": "OTHER", "authorizeType": 0}]}}
    print("  ->", {k: v for k, v in find_our_vehicle(mock_q).items() if k != "item"})

    print("== TEST find_our_vehicle: VIN solo in authorized, senza token ==")
    mock_q2 = {"code": "000000", "data": {"controlCarList": [],
        "authorizedControlCarList": [{"vin": "VIN_PLACEHOLDER", "authorizeType": 0}]}}
    print("  ->", {k: v for k, v in find_our_vehicle(mock_q2).items() if k != "item"})

    print("== TEST find_our_vehicle: VIN assente ==")
    print("  ->", {k: v for k, v in find_our_vehicle({"code": "000000", "data": {"controlCarList": []}}).items() if k != "item"})

    # NB: i mock vanno assegnati ai global di QUESTO modulo (__main__), che è ciò
    # che diagnose()/run_command() risolvono a runtime — non a un secondo `import`.
    print("== TEST diagnose (mock, ipotesi B) ==")
    W._bff_login = lambda: ("FAKE_UT", "FAKE_TUSERID")
    get_tuser_id = lambda user_id=None: (200, {"code": "000000", "data": "FAKE_TUSERID"})
    query_list   = lambda: (200, mock_q)
    print("  ->", diagnose(pub))

    print("== TEST diagnose (mock, ipotesi A: VIN presente, no token) ==")
    query_list = lambda: (200, mock_q2)
    print("  ->", diagnose(pub))

    print("== TEST run_command bloccato se no car_token (no rete comando) ==")
    query_list = lambda: (200, mock_q2)
    print("  ->", run_command(pub, cmd="remoteStart", is_awake=lambda: True))

    print("== TEST run_command flusso completo (mock, car_token presente) ==")
    query_list      = lambda: (200, mock_q)
    set_vec_default = lambda vin=None: (200, {"code": "000000"})
    check_password  = lambda tuser_id, pin=None, vin=None, scene=2: (200, {"code": "000000", "data": {"taskId": "TASK99"}}, "TASK99")
    sent = {}
    def fake_send(cmd, car_token, vin=None, tuser_id=None, task_id=None, extra_body=None):
        sent.update(cmd=cmd, car_token=car_token, task_id=task_id)
        return 200, {"code": "A00079"}
    send_command = fake_send
    print("  ->", run_command(pub, cmd="remoteStart", is_awake=lambda: True))
    print("     (comando inviato con car_token =", sent.get("car_token"), ", taskId =", sent.get("task_id"), ")")

    print("\nOK self-test concluso (nessuna chiamata di rete reale).")
