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
import os, json, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))

import requests

# P2-2: import relativi di pacchetto (prima: nomi nudi + `sys.path.insert(HERE)`).
from . import omoda_auth as A
from . import tsp_sign as S
from . import codes

# P2-6: VIN, TSP_HOST e il path del token NON sono più global di modulo riscritti prima
# di ogni chiamata: arrivano dal `CoreCtx` del veicolo (primo argomento di ogni funzione).
# Idem i lock, che erano di processo: due auto configurate se li contendevano senza
# alcun motivo, ed era il PRIMO entry a decidere il VIN per tutti.

COOLDOWN_S = int(os.environ.get("WAKE_COOLDOWN", "300"))   # min secondi tra due smsAwaken inviati
POLL_N     = int(os.environ.get("WAKE_POLL_N", "12"))      # n. cicli di poll
POLL_EVERY = int(os.environ.get("WAKE_POLL_EVERY", "5"))   # secondi tra un poll e l'altro


# ───────────────────────── cooldown della sveglia ────────────────────────────────
# Il cooldown vive nello stato del veicolo (in memoria). Prima stava in un file JSON
# condiviso da tutti i veicoli: con due auto, svegliarne una bloccava l'altra.
def _load_last_sms(ctx) -> float:
    return ctx.stato.ultimo_sms_ts

def _save_last_sms(ctx, ts: float):
    ctx.stato.ultimo_sms_ts = ts


# ───────────────────────── chiamate REST (patchabili nei test) ──────────────────
def _access_token(ctx):
    """Legge l'access_token dal token.json del veicolo. Difensivo: gestisce sia
    {data:{...}} sia il formato flat, e non esplode con KeyError se il campo manca
    (ritorna None). Unico punto di lettura del token: commands/provision usano questo."""
    with open(ctx.token_path) as fh:
        tok = json.load(fh)
    if not isinstance(tok, dict):
        return None
    d = tok.get("data", tok)
    if isinstance(d, dict) and d.get("access_token"):
        return d["access_token"]
    return tok.get("access_token")

def _refresh_token(ctx) -> bool:
    """Rinnova l'access_token col grant `refresh_token` (NIENTE OTP) e riscrive token.json.
    Stesso endpoint/headers del login OTP (login_otp.py), che NON è dietro il firewall Aliyun.
    Ritorna True se ha ottenuto un nuovo access_token, False altrimenti (es. refresh scaduto → serve OTP).

    C1: protetto da `_TOKEN_LOCK` con double-check. Fotografo l'access_token che il
    chiamante ha visto (PRIMA del lock); dentro il lock rileggo token.json: se sul
    disco l'access_token è già cambiato, un altro thread ha già rinnovato → NON rifaccio
    il refresh (rifarlo brucerebbe il nuovo refresh_token e invaliderebbe la sessione)."""
    # snapshot pre-lock: il token che il chiamante considerava scaduto
    try:
        with open(ctx.token_path) as fh:
            tok0 = json.load(fh)
    except Exception:
        return False
    seen_at = (tok0.get("data", tok0) or {}).get("access_token") if isinstance(tok0, dict) else None

    with ctx.stato.lock_token:
        # double-check DENTRO il lock: rileggo lo stato corrente del file
        try:
            with open(ctx.token_path) as fh:
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
            H = A.headers_post(TP, secret=A.SIGN_SECRET, ctx=ctx)
            r = requests.post(ctx.bff + TP, params=params, headers=H, timeout=20)
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
            path = ctx.token_path
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(j, f, ensure_ascii=False)
            os.chmod(tmp, 0o600)   # il token è una credenziale: leggibile solo dal proprietario
            os.replace(tmp, path)
        except Exception:
            return False
        return True

def _bff_login(ctx, _allow_refresh=True):
    """Ritorna (userToken, tUserId). Solleva su errore di rete; (None,None) se rifiutato.
    Se la sessione è scaduta tenta UN refresh_token automatico (senza OTP) e riprova una volta."""
    tok = _access_token(ctx)
    H = A.headers_post("/tsp/v1/app/auth/login", ctx=ctx, extra={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*"})
    r = requests.post(ctx.bff + "/tsp/v1/app/auth/login",
                      data=json.dumps({"channelId": ctx.channel_id}), headers=H, timeout=20)
    # token scaduto/424: il BFF può restituire un body il cui TOP-LEVEL è una stringa
    # (non un dict) → r.json() è un str e .get esploderebbe. Tratto tutto come sessione non valida.
    try:
        j = r.json()
    except Exception:
        return None, None
    d = j.get("data", {}) if isinstance(j, dict) else None
    # P1-3: il gate del refresh sta sull'ASSENZA di userToken, non sul solo `data` non-dict.
    # Prima, un `data` che ERA un dict ma senza userToken (es. {} o un body d'errore
    # strutturato) saltava del tutto il rinnovo → si tornava (None,None) e l'utente si vedeva
    # chiedere un OTP quando sarebbe bastato il refresh_token silenzioso.
    ut = d.get("userToken") if isinstance(d, dict) else None
    if not ut:
        # sessione scaduta: prova UN rinnovo automatico del token e ritenta una sola volta
        if _allow_refresh and _refresh_token(ctx):
            return _bff_login(ctx, _allow_refresh=False)
        return None, None
    return ut, d.get("tUserId")

def _signed_post(ctx, ut: str, path: str, params: dict):
    ts = int(time.time() * 1000)
    body = S.sign_body(dict(params), ts)
    headers = S.auth_headers(ut, ts)
    headers.update({"Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": "okhttp/4.9.0", "version": A.APP_VERSION, "agent": "android"})
    r = requests.post(ctx.tsp_host + path, data=json.dumps(body), headers=headers, timeout=25)
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
def do_wake(ctx, publish, is_awake=None, send_sms=True):
    """Esegue il flusso sveglia e riporta lo stato (stringhe già leggibili) via `publish`.

      ctx            -> CoreCtx del veicolo (VIN, host, token, cooldown)
      publish(text)  -> callback che scrive lo stato su HA + monitor (chiamata più volte)
      is_awake()     -> callback opzionale: True se il ponte sta già ricevendo eventi MQTT (auto sveglia)
      send_sms       -> se False NON invia davvero smsAwaken (solo per test/diagnostica)

    Ritorna un dict riepilogativo {ok, online, code, ...}. Mai solleva: ogni errore → status.
    """
    # lock PER VEICOLO: due auto possono svegliarsi in parallelo, la stessa no.
    if not ctx.stato.lock_sveglia.acquire(blocking=False):
        publish("⏳ Sveglia già in corso, attendi…")
        return {"ok": False, "reason": "busy"}
    try:
        return _do_wake_inner(ctx, publish, is_awake, send_sms)
    except Exception as e:
        publish(f"⚠️ Errore sveglia: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        ctx.stato.lock_sveglia.release()


def _do_wake_inner(ctx, publish, is_awake, send_sms):
    now = time.time()

    # 0) cooldown anti rate-limit (solo se invieremo davvero l'SMS)
    if send_sms:
        last = _load_last_sms(ctx)
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
    ut, tu = _bff_login(ctx)
    if not ut:
        publish("🔑 Sessione scaduta (token vecchio o app ufficiale aperta): rifai il login OTP")
        return {"ok": False, "reason": "no_usertoken"}

    # 2) smsAwaken (una sola volta)
    code = None
    if send_sms:
        sc, j = _signed_post(ctx, ut, "/asc/vehicleControl/smsAwaken", {"vin": ctx.vin})
        code = _code_of(j)
        _save_last_sms(ctx, time.time())     # registra SUBITO per il cooldown, anche se in errore
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
        sc1, j1 = _signed_post(ctx, ut, "/asr/manager/realtime", {"vin": ctx.vin})
        sc2, j2 = _signed_post(ctx, ut, "/asc/vehicleControl/queryVehicleLocation",
                               {"vin": ctx.vin})
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
    # L'orchestrazione si prova SENZA rete e SENZA inviare smsAwaken. Dopo P2-6 ogni
    # scenario ha il proprio contesto: prima si mutavano global di modulo, e un test
    # lasciava lo stato sporco per il successivo.
    from .context import CoreCtx

    def pub(t):
        print("  STATUS:", t)

    print("== TEST 1: auto gia' sveglia (is_awake=True) -> nessun SMS ==")
    print("  ->", do_wake(CoreCtx(vin="TEST"), pub, is_awake=lambda: True))

    print("== TEST 2: cooldown attivo ==")
    ctx = CoreCtx(vin="TEST")
    ctx.stato.ultimo_sms_ts = time.time() - 10
    print("  ->", do_wake(ctx, pub, is_awake=lambda: False))

    print("== TEST 3: token scaduto (bff_login -> None) ==")
    ctx = CoreCtx(vin="TEST")
    globals()["_bff_login"] = lambda c, _allow_refresh=True: (None, None)
    print("  ->", do_wake(ctx, pub, is_awake=lambda: False))
    print("\nOK self-test concluso (nessuna chiamata di rete reale).")
