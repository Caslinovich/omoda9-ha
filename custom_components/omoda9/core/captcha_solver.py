"""
captcha_solver.py — risolve l'AJ-Captcha blockPuzzle del gateway OMODA 'legend'.

Endpoint (scoperti decompilando l'app con blutter):
  POST /api/code/create  -> puzzle (originalImageBase64, jigsawImageBase64, secretKey, token)
  POST /api/code/check   -> verifica lo slide (pointJson cifrato)
Cifratura: AES/ECB/PKCS7, chiave = secretKey (UTF-8), output base64.
  pointJson           = AES( JSON({"x":gapX,"y":Y}) , secretKey )
  captchaVerification = AES( token + "---" + JSON({"x":gapX,"y":Y}) , secretKey )
Il captchaVerification va passato a sendMailCode/sendSmsCode.
"""
import os, time, hashlib, json, base64, io
import requests, numpy as np
from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
try:                        # importato come modulo del pacchetto (runtime HA)
    from . import omoda
except ImportError:         # eseguito come script: `login_omoda.py` gira in sottoprocesso
    import omoda

# NB (2026-06-21): il solver NON usa più OpenCV (cv2). Lo shape-matching è
# reimplementato con solo numpy + Pillow → installabile su Home Assistant/HAOS
# (numpy ha wheel per ogni arch, Pillow è già nel core di HA), così l'intero login
# OTP gira dentro HA per chi installa il componente senza un token preesistente.
# Equivalenza verificata A/B vs cv2 su captcha reali (9/10 x identici, il restante
# risolto MEGLIO dal numpy) + risolvi() end-to-end 5/5.

SECRET = "5c7af05e6fbf562842ef483ee96e06a0"   # secret di firma del gateway (universale)
NONCE  = "chery_legend_marketing"
ROOT   = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # regione (default EU)

def _md5(s): return hashlib.md5(s.encode()).hexdigest()

def _signed_headers(path):
    ts = int(time.time() * 1000)
    return {
        "Authorization": omoda.APP_BASIC, "tenant": omoda.TENANT_CODE,
        "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
        "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0",
        "nonce": NONCE, "timestamp": str(ts), "url": path,
        "signature": _md5(f"{SECRET}{NONCE}{path}{ts}"), "Content-Type": "application/json",
    }

def _aes_b64(plaintext, key):
    c = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    return base64.b64encode(c.encrypt(pad(plaintext.encode("utf-8"), 16))).decode()

def _img(b64): return Image.open(io.BytesIO(base64.b64decode(b64)))

def _dilate3(a):
    """Dilatazione 3×3 (8-vicini) — equivalente numpy di cv2.dilate(kernel 3×3)."""
    p = np.pad(a, 1, mode="edge")
    return np.maximum.reduce([p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                              p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                              p[2:, 0:-2],  p[2:, 1:-1],  p[2:, 2:]])

def _erode3(a):
    """Erosione 3×3 (8-vicini) — equivalente numpy di cv2.erode(kernel 3×3)."""
    p = np.pad(a, 1, mode="edge")
    return np.minimum.reduce([p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                              p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                              p[2:, 0:-2],  p[2:, 1:-1],  p[2:, 2:]])

def trova_gap_x(orig_b64, jigsaw_b64):
    """Ritorna pointJson x. Shape-matching: contorno del tassello vs contorni bianchi
    disegnati sullo sfondo (il vero buco ha la STESSA sagoma del tassello; le esche no).
    pointJson x = (bordo sinistro del buco) - (x0 del tassello nell'immagine jigsaw).

    Implementazione numpy-only (no cv2): bbox del tassello dall'alpha, gradiente
    morfologico 3×3 (dilate−erode) come template, normalized cross-correlation
    (TM_CCORR_NORMED) tramite sliding_window_view + einsum riga per riga (memoria O(W·h·w))."""
    o = np.asarray(_img(orig_b64).convert("RGB"))
    j = np.asarray(_img(jigsaw_b64).convert("RGBA"))
    m = (j[:, :, 3] > 128).astype(np.uint8)
    ys, xs = np.where(m)
    if ys.size == 0:
        return 0
    x, y = int(xs.min()), int(ys.min())
    w, h = int(xs.max()) - x + 1, int(ys.max()) - y + 1
    sil = m[y:y + h, x:x + w] * 255
    outline = np.clip(_dilate3(sil.astype(np.int16)) - _erode3(sil.astype(np.int16)),
                      0, 255).astype(np.float64)
    white = ((o[:, :, 0] > 185) & (o[:, :, 1] > 185) & (o[:, :, 2] > 185)).astype(np.float64)
    H, W = white.shape
    T = outline
    T2 = float((T * T).sum())
    if T2 <= 0 or H < h or W < w:
        return 0
    sw = np.lib.stride_tricks.sliding_window_view(white, (h, w))   # (H-h+1, W-w+1, h, w)
    best_score, best_x = -1.0, w
    for gy in range(sw.shape[0]):
        wr = sw[gy]                                  # (W-w+1, h, w)
        num = np.einsum("kij,ij->k", wr, T)
        den = np.sqrt(np.einsum("kij,kij->k", wr, wr) * T2)
        den[den == 0] = 1e-9
        res = num / den
        res[:max(1, w)] = 0                          # azzera il bordo sinistro (come l'orig.)
        gx = int(np.argmax(res))
        if res[gx] > best_score:
            best_score, best_x = float(res[gx]), gx
    return int(best_x) - x      # gapLeft - x0_jig

def crea():
    """Crea un puzzle. Ritorna repData (dict) o None se il gateway risponde
    non-JSON / shape inattesa (WAF Aliyun, manutenzione): il chiamante ritenta."""
    r = requests.post(f"{ROOT}/code/create", json={"captchaType": "blockPuzzle"},
                      headers=_signed_headers("/code/create"), timeout=15)
    try:
        return (r.json().get("data") or {}).get("repData")
    except Exception:
        return None

def _signed_headers_query(path, keys_csv, vals_csv):
    """Firma per richieste con parametri in QUERY: MD5(secret+nonce+path+ts+'[vals]') + header keys."""
    ts = int(time.time() * 1000)
    return {
        "Authorization": omoda.APP_BASIC, "tenant": omoda.TENANT_CODE,
        "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
        "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0",
        "nonce": NONCE, "timestamp": str(ts), "url": path, "keys": keys_csv,
        "signature": _md5(f"{SECRET}{NONCE}{path}{ts}[{vals_csv}]"), "Content-Type": "application/json",
    }

def check(token, point, secret):
    # I parametri vanno in QUERY (l'app usa encodeUrl -> ?captchaType=..&pointJson=..&token=..)
    point_json = json.dumps(point, separators=(",", ":"))
    enc = _aes_b64(point_json, secret)
    params = {"captchaType": "blockPuzzle", "pointJson": enc, "token": token}
    keys = "captchaType,pointJson,token"
    vals = f"blockPuzzle,{enc},{token}"
    r = requests.post(f"{ROOT}/code/check", params=params,
                      headers=_signed_headers_query("/code/check", keys, vals), timeout=15)
    try:
        j = r.json()
    except Exception:
        return {}
    return j if isinstance(j, dict) else {}

def risolvi(max_tentativi=12, verbose=True):
    """create+solve+check finche' non passa (token monouso). Ritorna captchaVerification o None.
    y del punto = 5 (costante, dalla decompilazione dell'app)."""
    for t in range(1, max_tentativi + 1):
        rep = crea()
        if not isinstance(rep, dict) or not all(
                rep.get(k) for k in ("token", "secretKey", "originalImageBase64", "jigsawImageBase64")):
            if verbose: print(f"  tentativo {t}: create non valido (gateway non-JSON?)")
            time.sleep(0.3)
            continue
        token, secret = rep["token"], rep["secretKey"]
        x = trova_gap_x(rep["originalImageBase64"], rep["jigsawImageBase64"])
        point = {"x": x, "y": 5}
        res = check(token, point, secret)
        d = res.get("data") or {}
        if d.get("repCode") == "0000":
            point_json = json.dumps(point, separators=(",", ":"))
            cv = _aes_b64(f"{token}---{point_json}", secret)
            if verbose: print(f"  ✅ captcha risolto al tentativo {t} (x={x}). cv={cv[:32]}…")
            return cv
        if verbose: print(f"  tentativo {t}: x={x} -> {d.get('repCode')} {d.get('repMsg')}")
        time.sleep(0.3)
    return None

if __name__ == "__main__":
    cv = risolvi()
    print("\nRISULTATO:", "OK -> " + cv if cv else "FALLITO")
