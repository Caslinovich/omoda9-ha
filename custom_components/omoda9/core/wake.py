#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wake.py — "Sveglia auto" Omoda 9: replica ESATTA del flusso dell'app ufficiale
          (1× smsAwaken → poll realtime/location), pensato per essere richiamato
          dal pulsante Home Assistant esposto da ha_bridge.py.

Flusso (verificato sul codice reale, SESSIONE11_REPORT.md):
  1) bff_login()  : token.json (access_token) → POST {BFF}/tsp/v1/app/auth/login → userToken/tUserId
  2) smsAwaken    : POST {TSP}/asc/vehicleControl/smsAwaken {vin}, firmato tsp_sign
                    code "000000" = sveglia accettata; "A07312" = rate-limit/quota SMS-wake.
  3) poll ~60s    : /asr/manager/realtime + /asc/vehicleControl/queryVehicleLocation ogni 5s.
                    In parallelo il listener MQTT del ponte cattura i 5A02 → is_awake() diventa True.

⚠️  smsAwaken HA UN RATE-LIMIT REALE. Il pulsante NON va martellato:
    - `do_wake` rispetta un COOLDOWN (default 300s) tra due smsAwaken davvero inviati;
    - un solo `do_wake` per volta (lock anti doppio-tap).

Uso strettamente personale (auto/account di Rino). NON pubblicare token/cert.
"""
import os, sys, json, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import requests
import omoda_auth as A
import tsp_sign as S
import codes

# C1: serializza i refresh del token. keep-alive (coordinator) e un comando possono
# innescare _refresh_token() insieme: senza lock entrambi userebbero lo STESSO
# refresh_token, Chery lo ruota a ogni uso → il secondo refresh invalida il token
# del primo e la sessione cade. Il lock + double-check (sotto) evita il doppio refresh.
_TOKEN_LOCK = threading.Lock()

TSP_HOST   = os.environ.get("TSP_HOST", "https://tspconsole-eu.cheryinternational.com")   # regione (default EU)
VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: vedi omoda9.env.example


def _token_path() -> str:
    """Path del token canonico, riletto da env a OGNI accesso (NON congelato all'import).

    Necessario perché core/ viene importato una sola volta nel processo HA ma con
    contesti diversi: il config flow conia il token in un path 'pending', il runtime
    usa quello per-VIN. Leggere TOKEN_PATH a import-time darebbe il path sbagliato
    (es. la verifica post-OTP leggeva il vecchio token per-VIN già invalidato)."""
    return os.environ.get("OMODA_TOKEN_PATH") or os.path.join(HERE, "token.json")


# Compat: alcune chiamate storiche usano wake.TOKEN_PATH come valore iniziale.
TOKEN_PATH = _token_path()
# stato persistente del cooldown (sopravvive ai riavvii del ponte)
WAKE_STATE = os.environ.get("OMODA_WAKE_STATE", os.path.join(HERE, "data", "wake_state.json"))

COOLDOWN_S = int(os.environ.get("WAKE_COOLDOWN", "300"))   # min secondi tra due smsAwaken inviati
POLL_N     = int(os.environ.get("WAKE_POLL_N", "12"))      # n. cicli di poll
POLL_EVERY = int(os.environ.get("WAKE_POLL_EVERY", "5"))   # secondi tra un poll e l'altro

_BUSY = threading.Lock()   # un solo wake per volta


# ───────────────────────── persistenza cooldown ────────────────────────────────
def _load_last_sms() -> float:
    try:
        with open(WAKE_STATE, "r", encoding="utf-8") as f:
            return float(json.load(f).get("last_sms_ts", 0.0))
    except Exception:
        return 0.0

def _save_last_sms(ts: float):
    try:
        os.makedirs(os.path.dirname(WAKE_STATE), exist_ok=True)
        with open(WAKE_STATE, "w", encoding="utf-8") as f:
            json.dump({"last_sms_ts": ts}, f)
    except Exception:
        pass


# ───────────────────────── chiamate REST (patchabili nei test) ──────────────────
def _access_token():
    """Legge l'access_token dal token.json. Difensivo: gestisce sia {data:{...}} sia
    il formato flat, e non esplode con KeyError se il campo manca (ritorna None).
    Unico punto di lettura del token: commands/provision usano questo."""
    with open(_token_path()) as fh:
        tok = json.load(fh)
    if not isinstance(tok, dict):
        return None
    d = tok.get("data", tok)
    if isinstance(d, dict) and d.get("access_token"):
        return d["access_token"]
    return tok.get("access_token")

def _refresh_token() -> bool:
    """Rinnova l'access_token col grant `refresh_token` (NIENTE OTP) e riscrive token.json.
    Stesso endpoint/headers del login OTP (login_otp.py), che NON è dietro il firewall Aliyun.
    Ritorna True se ha ottenuto un nuovo access_token, False altrimenti (es. refresh scaduto → serve OTP).

    C1: protetto da `_TOKEN_LOCK` con double-check. Fotografo l'access_token che il
    chiamante ha visto (PRIMA del lock); dentro il lock rileggo token.json: se sul
    disco l'access_token è già cambiato, un altro thread ha già rinnovato → NON rifaccio
    il refresh (rifarlo brucerebbe il nuovo refresh_token e invaliderebbe la sessione)."""
    # snapshot pre-lock: il token che il chiamante considerava scaduto
    try:
        with open(_token_path()) as fh:
            tok0 = json.load(fh)
    except Exception:
        return False
    seen_at = (tok0.get("data", tok0) or {}).get("access_token") if isinstance(tok0, dict) else None

    with _TOKEN_LOCK:
        # double-check DENTRO il lock: rileggo lo stato corrente del file
        try:
            with open(_token_path()) as fh:
                tok = json.load(fh)
        except Exception:
            return False
        d = (tok.get("data", tok) or {}) if isinstance(tok, dict) else {}
        cur_at = d.get("access_token")
        if seen_at and cur_at and cur_at != seen_at:
            # già rinnovato da un altro thread: il token su disco è valido, non toccarlo
            return True
        rt = d.get("refresh_token")
        if not rt:
            return False
        # Ricetta verificata (= identica all'OTP login di prova_token.py): firma applicativa
        # via headers_post + parametri in QUERY STRING. Senza firma il gateway risponde 428.
        TP = "/auth/oauth2/token"
        params = {"grant_type": "refresh_token", "refresh_token": rt, "scope": "server"}
        try:
            H = A.headers_post(TP, secret=A.SIGN_SECRET)
            r = requests.post(A.BFF + TP, params=params, headers=H, timeout=20)
            j = r.json()
        except Exception:
            return False
        if not isinstance(j, dict):
            return False
        at = j.get("access_token") or (j.get("data") or {}).get("access_token")
        if not at:
            return False
        # scrittura atomica: nuovo token su file temporaneo poi rename (token.json mai corrotto)
        try:
            path = _token_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            return False
        return True

def _bff_login(_allow_refresh=True):
    """Ritorna (userToken, tUserId). Solleva su errore di rete; (None,None) se rifiutato.
    Se la sessione è scaduta tenta UN refresh_token automatico (senza OTP) e riprova una volta."""
    tok = _access_token()
    H = A.headers_post("/tsp/v1/app/auth/login", extra={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*"})
    r = requests.post(A.BFF + "/tsp/v1/app/auth/login",
                      data=json.dumps({"channelId": A.CHANNEL_ID}), headers=H, timeout=20)
    # token scaduto/424: il BFF può restituire un body il cui TOP-LEVEL è una stringa
    # (non un dict) → r.json() è un str e .get esploderebbe. Tratto tutto come sessione non valida.
    try:
        j = r.json()
    except Exception:
        return None, None
    d = j.get("data", {}) if isinstance(j, dict) else None
    if not isinstance(d, dict):
        # sessione scaduta: prova UN rinnovo automatico del token e ritenta una sola volta
        if _allow_refresh and _refresh_token():
            return _bff_login(_allow_refresh=False)
        return None, None
    return d.get("userToken"), d.get("tUserId")

def _signed_post(ut: str, path: str, params: dict):
    ts = int(time.time() * 1000)
    body = S.sign_body(dict(params), ts)
    headers = S.auth_headers(ut, ts)
    headers.update({"Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": "okhttp/4.9.0", "version": A.APP_VERSION, "agent": "android"})
    r = requests.post(TSP_HOST + path, data=json.dumps(body), headers=headers, timeout=25)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:300]}

def _code_of(j):
    return j.get("code") if isinstance(j, dict) else j

def _payload(j):
    """Payload utile della risposta tspconsole: sotto "data" su alcuni endpoint e
    sotto "body" su altri (es. /asr/manager/realtime → "body" con 84 campi). Ritorna
    il primo dict non vuoto, o None."""
    if not isinstance(j, dict):
        return None
    for k in ("data", "body"):
        v = j.get(k)
        if isinstance(v, dict) and v:
            return v
    return None


def _has_live_data(j):
    return _payload(j) is not None


# ───────────────────────── orchestrazione del pulsante ──────────────────────────
def do_wake(publish, is_awake=None, send_sms=True):
    """Esegue il flusso sveglia e riporta lo stato (stringhe già leggibili) via `publish`.

      publish(text)  -> callback che scrive lo stato su HA + monitor (chiamata più volte)
      is_awake()     -> callback opzionale: True se il ponte sta già ricevendo eventi MQTT (auto sveglia)
      send_sms       -> se False NON invia davvero smsAwaken (solo per test/diagnostica)

    Ritorna un dict riepilogativo {ok, online, code, ...}. Mai solleva: ogni errore → status.
    """
    if not _BUSY.acquire(blocking=False):
        publish("⏳ Sveglia già in corso, attendi…")
        return {"ok": False, "reason": "busy"}
    try:
        return _do_wake_inner(publish, is_awake, send_sms)
    except Exception as e:
        publish(f"⚠️ Errore sveglia: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        _BUSY.release()


def _do_wake_inner(publish, is_awake, send_sms):
    now = time.time()

    # 0) cooldown anti rate-limit (solo se invieremo davvero l'SMS)
    if send_sms:
        last = _load_last_sms()
        wait = COOLDOWN_S - (now - last)
        if last and wait > 0:
            mm, ss = divmod(int(wait), 60)
            publish(f"⏳ Anti rate-limit: aspetta ancora {mm}m{ss:02d}s prima di risvegliare di nuovo")
            return {"ok": False, "reason": "cooldown", "wait_s": int(wait)}

    # se l'auto sta già pubblicando su MQTT, è già sveglia: niente SMS
    if is_awake and is_awake():
        publish("🟢 Auto già sveglia (sta inviando dati) — sveglia non necessaria")
        return {"ok": True, "online": True, "reason": "already_awake"}

    # 1) login BFF → userToken
    publish("🔑 Accesso in corso…")
    ut, tu = _bff_login()
    if not ut:
        publish("🔑 Sessione scaduta (token vecchio o app ufficiale aperta): rifai il login OTP")
        return {"ok": False, "reason": "no_usertoken"}

    # 2) smsAwaken (una sola volta)
    code = None
    if send_sms:
        sc, j = _signed_post(ut, "/asc/vehicleControl/smsAwaken", {"vin": VIN})
        code = _code_of(j)
        _save_last_sms(time.time())     # registra SUBITO per il cooldown, anche se in errore
        if str(code) in ("000000", "A00079"):
            publish("✅ Sveglia inviata — attendo che l'auto si connetta…")
        elif str(code) == "A07312":
            publish("🚫 Rate-limit sveglia (A07312): l'auto rifiuta altre sveglie ora. Riprova più tardi")
            return {"ok": False, "online": False, "code": code, "reason": "rate_limit"}
        else:
            publish(f"⚠️ Sveglia non accettata ({code}: {codes.meaning(code)}). Provo comunque ad ascoltare…")
    else:
        publish("🧪 (test) smsAwaken NON inviato; passo solo al poll")

    # 3) poll realtime/location + ascolto MQTT, per ~POLL_N*POLL_EVERY secondi
    for i in range(POLL_N):
        if is_awake and is_awake():
            publish("🟢 Auto ONLINE — sta inviando dati in tempo reale")
            return {"ok": True, "online": True, "code": code, "via": "mqtt"}
        sc1, j1 = _signed_post(ut, "/asr/manager/realtime", {"vin": VIN})
        sc2, j2 = _signed_post(ut, "/asc/vehicleControl/queryVehicleLocation", {"vin": VIN})
        if _has_live_data(j1) or _has_live_data(j2):
            publish("🟢 Auto ONLINE — dati realtime ricevuti")
            return {"ok": True, "online": True, "code": code, "via": "rest",
                    "data": _payload(j1) or _payload(j2)}
        secs_left = (POLL_N - i - 1) * POLL_EVERY
        publish(f"… in attesa risveglio ({_code_of(j1)}) — ancora ~{secs_left}s")
        time.sleep(POLL_EVERY)

    publish("⌛ Auto ancora a riposo (A07900). Riprova quando è stata usata di recente o ha buon segnale")
    return {"ok": True, "online": False, "code": code, "reason": "still_asleep"}


# ───────────────────────── self-test (NESSUNA chiamata di rete) ─────────────────
if __name__ == "__main__":
    # Test dell'orchestrazione SENZA toccare la rete né inviare smsAwaken.
    import wake as W
    msgs = []
    pub = lambda t: (msgs.append(t), print("  STATUS:", t))[1]

    print("== TEST 1: auto già sveglia (is_awake=True) → nessun SMS ==")
    msgs.clear()
    print("  ->", W.do_wake(pub, is_awake=lambda: True, send_sms=True))

    print("== TEST 2: cooldown attivo ==")
    msgs.clear()
    W._load_last_sms = lambda: time.time() - 10   # ultimo SMS 10s fa
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))

    print("== TEST 3: flusso completo MOCK (no rete): smsAwaken=000000, poi MQTT sveglio ==")
    msgs.clear()
    W._load_last_sms = lambda: 0.0
    W._save_last_sms = lambda ts: None
    W._bff_login = lambda: ("FAKE_USERTOKEN", "FAKE_TUSERID")
    calls = {"n": 0}
    def fake_post(ut, path, params):
        calls["n"] += 1
        if path.endswith("smsAwaken"):
            return 200, {"code": "000000"}
        return 200, {"code": "A07900"}   # realtime/location ancora offline
    W._signed_post = fake_post
    awake_state = {"v": False}
    def fake_awake():
        # diventa sveglia dopo il 2° giro di poll
        awake_state["v"] = calls["n"] >= 3
        return awake_state["v"]
    W.POLL_EVERY = 0    # test veloce
    print("  ->", W.do_wake(pub, is_awake=fake_awake, send_sms=True))

    print("== TEST 4: token scaduto (bff_login → None) ==")
    msgs.clear()
    W._bff_login = lambda: (None, None)
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))

    print("== TEST 5: rate-limit A07312 ==")
    msgs.clear()
    W._bff_login = lambda: ("FAKE", "1")
    W._signed_post = lambda ut, path, params: (200, {"code": "A07312"})
    print("  ->", W.do_wake(pub, is_awake=lambda: False, send_sms=True))
    print("\nOK self-test concluso (nessuna chiamata di rete reale).")
