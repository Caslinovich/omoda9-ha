#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py — "Sonda posizione" Omoda 9.

Domanda a cui risponde (mai testata pulita finora): quando l'auto è DAVVERO
sveglia (sta pubblicando 5A02 su MQTT), il canale tspconsole-eu restituisce
posizione GPS / dati realtime, oppure ancora `A07900`?

Scoperta SESSIONE 14 (verificata sul codice di ENTRAMBE le app, EU + russa):
  - NON esiste un endpoint BFF per i comandi. Il BFF "legend" ha solo
    auth/cpm(PIN)/env/map/vac/vmc. I comandi/posizione passano TUTTI dalla SDK
    Chery → tspconsole-eu `/asc/vehicleControl/*` e `/asr/manager/realtime`,
    cioè ESATTAMENTE i path che già usiamo. Niente canale nascosto.
  - Quindi l'unica variabile che resta è lo STATO SVEGLIA dell'auto. L'app
    riesce perché comanda ad auto appena usata; noi cadiamo su A07900 (dorme)
    e non possiamo svegliarla (smsAwaken in A07312, quota per-account).

Questa sonda è di SOLA LETTURA: chiama `/asr/manager/realtime {vin}` e
`/asc/vehicleControl/queryVehicleLocation {vin}` (gli stessi del poll di
wake.py). NON invia smsAwaken, NON manda comandi, NON tocca il PIN. È benigna:
è ciò che l'app fa quando apri la pagina "posizione".

Va richiamata dal ponte (ha_bridge.py) al fronte di salita asleep→awake, con
un cooldown lungo (default 30 min) per non ripetere a ogni 5A02.

Uso strettamente personale (auto/account di Rino). NON pubblicare token/cert.
"""
import os, sys, json, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Riusa l'infrastruttura già verificata di wake.py: login BFF + POST firmato tspconsole.
import wake as W
import codes

VIN        = os.environ.get("VIN", "")   # PER-ACCOUNT: vedi omoda9.env.example
PROBE_LOG  = os.environ.get("OMODA_PROBE_LOG", os.path.join(HERE, "data", "probe.jsonl"))
COOLDOWN_S = int(os.environ.get("PROBE_COOLDOWN", "120"))   # [2.0] 2 min: il realtime è read-only e l'auto resta online a lungo → letture opportunistiche frequenti (era 1800=30min, troppo restrittivo). I poll usano force=True e lo bypassano comunque.

_BUSY = threading.Lock()
_last_run = {"ts": 0.0}

# campi "ricchi" del CVRealtimeResBean che ci interessano di più (se mai arrivano)
RICH_KEYS = ("lat", "lon", "altitude", "direction", "gpsSpeed", "vehicleSpeed",
             "odometer", "dumpEnergy", "electricRange", "pureElectricRange",
             "chargeState", "inCarTemperature", "onlineStatus")


def _log(rec: dict):
    rec = {"ts": round(time.time(), 3),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()), **rec}
    try:
        os.makedirs(os.path.dirname(PROBE_LOG), exist_ok=True)
        with open(PROBE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rich(data: dict) -> dict:
    """Estrae i campi interessanti se presenti, per il riepilogo leggibile."""
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in RICH_KEYS if k in data}


def probe_once(publish, force=False, on_data=None):
    """Esegue UNA sonda di sola lettura e riporta l'esito via `publish(text)`.

    Ritorna un dict {ok, online, got_data, codes, rich}. Mai solleva.
    `force=True` ignora il cooldown (per il test manuale).
    `on_data(data)` (opzionale): callback invocata col dict `data` grezzo SOLO quando
    si ricevono dati live (auto sveglia) — il ponte la usa per pubblicare GPS/batteria in HA.
    """
    if not _BUSY.acquire(blocking=False):
        return {"ok": False, "reason": "busy"}
    try:
        now = time.time()
        if not force and _last_run["ts"] and (now - _last_run["ts"]) < COOLDOWN_S:
            return {"ok": False, "reason": "cooldown",
                    "wait_s": int(COOLDOWN_S - (now - _last_run["ts"]))}
        _last_run["ts"] = now

        publish("🛰️ Sonda posizione: l'auto è sveglia, provo a leggere GPS/realtime…")
        ut, tu = W._bff_login()
        if not ut:
            publish("🔑 Sonda: sessione scaduta (rifai login OTP). Riprovo al prossimo risveglio")
            _log({"event": "probe", "ok": False, "reason": "no_usertoken"})
            return {"ok": False, "reason": "no_usertoken"}

        sc1, j1 = W._signed_post(ut, "/asr/manager/realtime", {"vin": VIN})
        sc2, j2 = W._signed_post(ut, "/asc/vehicleControl/queryVehicleLocation", {"vin": VIN})
        # travelQuery: cerchiamo km/odometro (campo non ancora visto; lo riveleremo al 1° wake reale)
        sc3, j3 = W._signed_post(ut, "/asd/travelManage/travelQuery", {"vin": VIN})
        c1, c2, c3 = W._code_of(j1), W._code_of(j2), W._code_of(j3)
        got1, got2, got3 = W._has_live_data(j1), W._has_live_data(j2), W._has_live_data(j3)

        # data combinato: realtime ha priorità (lat/lon/batteria), travel/location aggiungono campi extra.
        # Il payload sta sotto "data" o "body" a seconda dell'endpoint (realtime → "body"): W._payload
        # li gestisce entrambi, altrimenti i 84 campi realtime venivano persi.
        data = {}
        for src, got in ((j2, got2), (j3, got3), (j1, got1)):
            payload = W._payload(src)
            if got and isinstance(payload, dict):
                data.update(payload)
        rich = _rich(data)
        _log({"event": "probe", "ok": True, "realtime_code": c1, "location_code": c2,
              "travel_code": c3, "got_realtime": got1, "got_location": got2, "got_travel": got3,
              "rich": rich, "data": data or None,
              "travel_data": j3.get("data") if got3 else None})

        got1 = got1 or got3   # se travelQuery porta dati ad auto sveglia, vale come "live"
        if (got1 or got2) and on_data and data:
            try:
                on_data(data)
            except Exception as e:
                publish(f"⚠️ Sonda: errore pubblicazione dati ({type(e).__name__})")

        if got1 or got2:
            if rich:
                bits = ", ".join(f"{k}={v}" for k, v in rich.items())
                publish(f"🟢🛰️ SVOLTA: dati realtime ricevuti ad auto sveglia! {bits}")
            else:
                publish("🟢🛰️ Sonda: dati ricevuti ad auto sveglia (vedi data/probe.jsonl)")
            return {"ok": True, "online": True, "got_data": True,
                    "codes": [c1, c2, c3], "rich": rich}

        publish(f"🟡 Sonda: ancora niente posizione ad auto sveglia "
                f"(realtime={c1} [{codes.meaning(c1)}], location={c2}, travel={c3}). "
                "Confermato: serve un altro passo")
        return {"ok": True, "online": False, "got_data": False, "codes": [c1, c2, c3]}
    except Exception as e:
        publish(f"⚠️ Sonda errore: {type(e).__name__}: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        _BUSY.release()


# ───────────────────────── self-test (NESSUNA rete) ─────────────────────────────
if __name__ == "__main__":
    pub = lambda t: print("  STATUS:", t)

    print("== TEST 1: dati realtime ricevuti (mock) → SVOLTA ==")
    W._bff_login = lambda: ("FAKE_UT", "1")
    W._signed_post = lambda ut, path, params: (200, {"code": "000000", "data": {
        "lat": "45.07", "lon": "7.68", "dumpEnergy": "82", "vehicleSpeed": "0",
        "onlineStatus": "1"}}) if "realtime" in path else (200, {"code": "A07900"})
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))

    print("== TEST 2: ancora A07900 ad auto sveglia (mock) ==")
    W._signed_post = lambda ut, path, params: (200, {"code": "A07900"})
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))

    print("== TEST 3: cooldown attivo ==")
    _last_run["ts"] = time.time()
    print("  ->", probe_once(pub))

    print("== TEST 4: token scaduto ==")
    W._bff_login = lambda: (None, None)
    _last_run["ts"] = 0.0
    print("  ->", probe_once(pub, force=True))
    print("\nOK self-test concluso (nessuna chiamata di rete reale).")
