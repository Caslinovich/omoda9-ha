"""
prova_token.py — chiama auth/oauth2/token replicando l'app.

  python3 prova_token.py <email> <code> [secret] [emailfmt] [codefmt]

  secret:   prod (default) | test | h5md5   (h5md5 = vecchio schema MD5/5c7af05e)
  emailfmt: module (default, "APP-LOGIN@<email>") | plain
  codefmt:  plain (default) | padRight32 | padLeft32 | raw  (raw = code non cifrato)

Per testare la FIRMA senza consumare OTP: usa un <code> finto (es. 000000).
Se la firma e' giusta l'errore NON sara' piu' "Authorization authentication failed".
"""
import os, sys, json, requests
# Eseguito COME SCRIPT in sottoprocesso (session.confirm_otp): import relativo con
# ripiego su quello nudo, così funziona sia importato sia lanciato da riga di comando.
try:
    from . import omoda_auth as A
except ImportError:
    import omoda_auth as A

# dove salvare il token coniato (per-account); il bridge/coordinator legge lo stesso path
_TOKEN_OUT = os.environ.get("OMODA_TOKEN_PATH", "token.json")

TOKEN_PATH = "/auth/oauth2/token"

def build_params(email, code, emailfmt, codefmt):
    em = f"APP-LOGIN@{email}" if emailfmt=="module" else email
    cv = code if codefmt=="raw" else A.sm4_code(code, codefmt)
    # ordine come nel builder app: email, code, needDecode, grant_type, scope, loginType, loginAction
    return {
        "email": em,
        "code": cv,
        "needDecode": "0",
        "grant_type": "email",
        "scope": "server",
        "loginType": "email",
        "loginAction": "1",
    }

def call(email, code, secret="prod", emailfmt="module", codefmt="plain", verbose=True):
    sec = {"prod": A.SIGN_SECRET, "test": A.SIGN_SECRET_TEST}.get(secret)
    params = build_params(email, code, emailfmt, codefmt)
    if secret == "h5md5":
        # vecchio schema MD5/5c7af05e/marketing, niente brackets (POST)
        import hashlib, time
        ts = int(time.time()*1000)
        S, N = "5c7af05e6fbf562842ef483ee96e06a0", "chery_legend_marketing"
        sig = hashlib.md5(f"{S}{N}{TOKEN_PATH}{ts}".encode()).hexdigest()
        H = A.headers_post(TOKEN_PATH)  # base
        H.update({"nonce": N, "timestamp": str(ts), "signature": sig})
    else:
        H = A.headers_post(TOKEN_PATH, secret=sec)
    r = requests.post(A.BFF + "/auth/oauth2/token", params=params, headers=H, timeout=20)
    try: j = r.json()
    except Exception: j = {"_raw": r.text[:300]}
    tok = j.get("access_token") or (j.get("data") or {}).get("access_token")
    if verbose:
        # LOW: lo stdout di questo script passa per HA → redigi i token nei dump
        print(f"[secret={secret} email={emailfmt} code={codefmt}] HTTP {r.status_code}")
        print("  url:", r.url)
        print("  resp:", json.dumps(_redact(j), ensure_ascii=False)[:400])
    return r.status_code, j, tok


def _redact(obj):
    """Copia con access_token/refresh_token oscurati (per le stampe che vanno in HA)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("access_token", "refresh_token") and v:
                out[k] = f"<{len(str(v))}ch redatto>"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj

if __name__ == "__main__":
    # P1-4: email e codice OTP possono arrivare dall'ambiente (OMODA_EMAIL/OMODA_OTP) invece
    # che da argv → non compaiono in `ps`/`/proc/<pid>/cmdline`. argv resta per l'uso a mano.
    email = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OMODA_EMAIL", "")
    code = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("OMODA_OTP", "")
    if not (email and code):
        print(__doc__); sys.exit(1)
    secret  = sys.argv[3] if len(sys.argv) > 3 else "prod"
    emailfmt= sys.argv[4] if len(sys.argv) > 4 else "module"
    codefmt = sys.argv[5] if len(sys.argv) > 5 else "plain"
    sc, j, tok = call(email, code, secret, emailfmt, codefmt)
    if tok:
        # scrittura atomica: tmp + rename (token.json mai troncato se il processo muore)
        tmp = _TOKEN_OUT + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(j, fh, indent=2, ensure_ascii=False)
        os.chmod(tmp, 0o600)   # il token è una credenziale: leggibile solo dal proprietario
        os.replace(tmp, _TOKEN_OUT)
        print(f"\n✅ LOGIN OK — token salvato in {_TOKEN_OUT}")
        print("RESULT: OK")          # H7: sentinella stabile per session.confirm_otp
        sys.exit(0)
    # H7: conio fallito → sentinella + exit code != 0 (session.py si basa su questi)
    print("RESULT: FAIL")
    sys.exit(1)
