#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tsp_sign.py — Firma REST della Chery Vehicle SDK (PROD EU), ricostruita
byte-per-byte dallo smali `smali_dex2/h/ldkb.smali` (sessione 8, 2026-06-17):

  - metodo b(Map,J,String)  : costruisce la stringa-da-firmare
  - metodo c(String)        : SHA-256 -> hex -> toUpperCase()  (MAIUSCOLO!)
  - metodo a(Map,J,String)  : per tagEncrypt="1" aggiunge appId, firma, aggiunge sign
  - metodo a(J,String)      : header Authorization=token, timestamp, x-TenantId=""

Algoritmo (EU, tagEncrypt="1"):
  half      = caratteri di posizione PARI di APP_SECRET (-> "EUProd89ec59274d23491084af")
  base      = <param ordinati alfab. "k=v&" non-vuoti> + "secretKey=" + half + "&timestamp=" + ts
  sign      = SHA256(base) in HEX MAIUSCOLO
  body JSON = { ...params..., "appId": <APP_ID>, "sign": <sign> }
  header    = { Authorization: <userToken>, timestamp: <ts>, x-TenantId: "" }
"""
import os
import hashlib
import base64

# Costanti di REGIONE (environments[0] in Config.java). Default EU, override via env.
APP_ID     = os.environ.get("TSP_APP_ID", "eu-1")
APP_SECRET = "EBUJPYr7oDd48C9Te9c755942Y7T48dV293Y4Z931J098X41aYf0"
TAG_ENCRYPT = "1"          # EU = SHA-256 (NON HMAC)

def half_secret(secret: str = APP_SECRET) -> str:
    """Caratteri di posizione PARI (indici 0,2,4,...) -> 'EUProd89ec59274d23491084af'."""
    return "".join(secret[i] for i in range(len(secret)) if i % 2 == 0)

HALF = half_secret()   # "EUProd89ec59274d23491084af"

def _flatten_value(v):
    """Serializza un valore-ARRAY annidato come fa il SDK nativo (a(JSONObject) in
    ldkb.smali) PRIMA del calcolo del sign. Per ogni elemento:
      - oggetto  → 'chiave=valore&' con chiavi ordinate alfab. (valori vuoti saltati),
                   e la sua eventuale sotto-lista appiattita ricorsivamente;
      - scalare  → str(elemento) concatenato SENZA separatore (es. [1,2,3] → '123').
    Il '&' finale viene rimosso. Verificato byte-per-byte su 4/4 envelope reali
    `chargeAppointControl` (cycleData [1..7] → '1234567')."""
    if isinstance(v, list):
        sb = ""
        for el in v:
            if isinstance(el, dict):
                fl = _flatten_obj(el)
                for k in sorted(fl.keys()):
                    val = fl[k]
                    if val is None or val == "":
                        continue
                    sb += f"{k}={val}&"
            else:
                sb += str(el)
        if sb.endswith("&"):
            sb = sb[:-1]
        return sb
    return v


def _flatten_obj(obj: dict) -> dict:
    """Copia dell'oggetto con i soli valori-lista appiattiti (vedi _flatten_value).
    I valori scalari restano invariati → per i body PIATTI è un no-op (l'algoritmo
    storico resta identico, verificato su 63/63 envelope piatti)."""
    return {k: (_flatten_value(v) if isinstance(v, list) else v) for k, v in obj.items()}


def build_sign(params: dict, ts_ms: int, half: str = HALF) -> str:
    """Replica b(Map,J,String) per tagEncrypt='1': SHA-256 MAIUSCOLO.

    I valori-array annidati (es. `chargeAppointPlans`) vengono prima appiattiti come
    fa il SDK nativo (_flatten_obj); senza array il comportamento è invariato. NB:
    appiattisce una COPIA → il body restituito da sign_body conserva l'array reale."""
    flat = _flatten_obj(params)
    parts = []
    for k in sorted(flat.keys()):                # Arrays.sort sulle chiavi
        v = flat[k]
        if v is None or v == "":                 # null/"" saltati
            continue
        parts.append(f"{k}={v}&")
    base = "".join(parts) + f"secretKey={half}&timestamp={ts_ms}"
    # SCOPERTA S23 (2026-06-20, cattura eCapture/Conscrypt): l'encoding REALE del sign
    # e' base64(sha256(base)).upper(), NON hexdigest().upper(). Verificato su 71 envelope
    # reali (airControl/coolingControl/heatingControl/lockControl/seatControl/window/findCar...).
    return base64.b64encode(hashlib.sha256(base.encode("utf-8")).digest()).decode().upper()

def sign_body(body_params: dict, ts_ms: int) -> dict:
    """Replica a(Map,J,String) tag1: ritorna il body JSON finale {params, appId, sign}."""
    m = dict(body_params)
    m["appId"] = APP_ID                          # appId nei parametri firmati
    sign = build_sign(m, ts_ms)
    m["sign"] = sign                             # sign aggiunto DOPO la firma
    return m

def auth_headers(user_token: str, ts_ms: int, tenant_id: str = "") -> dict:
    """Replica a(J,String) tag1: Authorization=token, timestamp, x-TenantId."""
    return {
        "Authorization": user_token,
        "timestamp": str(ts_ms),
        "x-TenantId": tenant_id or "",
    }

if __name__ == "__main__":
    print("HALF =", HALF, "(atteso EUProd89ec59274d23491084af)")
    ts = 1700000000000
    demo = sign_body({"vin": "VIN_PLACEHOLDER"}, ts)
    print("demo body:", demo)
