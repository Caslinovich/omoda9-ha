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
    from . import mask
except ImportError:
    import omoda_auth as A
    import mask

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

def _dept(area):
    """`DEPT-ID` da mandare nelle intestazioni, ricavato dal prefisso internazionale.

    Quel campo è il prefisso del Paese (Italia 39, Francia 33, Germania 49) e qui veniva
    lasciato al default italiano anche per chi accede con un numero straniero. Questo modulo
    gira come sottoprocesso senza `CoreCtx`, quindi il valore va passato a mano: il prefisso
    ce l'ha già, ed è il momento in cui conta di più — il conio del token.
    Dizionario vuoto se non c'è nulla di sensato: così vale il default di `omoda_auth`."""
    cifre = "".join(ch for ch in str(area or "") if ch.isdigit()).lstrip("0")
    return {"dept_id": cifre} if cifre else {}


def build_params_mobile(phone, area, code, codefmt="plain"):
    """Parametri per il login MOBILE (SMS). Forma ESATTA dell'app, dal dump Dart
    `UserService::phoneVerifyLogin`: l'identità è la stringa COMPOSITA
    `APP-LOGIN@<numeroNazionale>_<areaCode>` (NON il numero nudo) e il codice è SM4 come
    l'email. NB: questi vanno inviati nel BODY, non in query (vedi `call`)."""
    phone = str(phone).lstrip("+").replace(" ", "")
    cv = code if codefmt == "raw" else A.sm4_code(code, codefmt)
    return {
        "mobile": f"APP-LOGIN@{phone}_{area}",
        "code": cv,
        "needDecode": "0",
        "grant_type": "mobile",
        "scope": "server",
        "loginType": "mobile",
        "loginAction": "1",
    }


def call(email, code, secret="prod", emailfmt="module", codefmt="plain", verbose=True,
         phone="", area="39"):
    sec = {"prod": A.SIGN_SECRET, "test": A.SIGN_SECRET_TEST}.get(secret)
    is_mobile = bool(phone)
    if is_mobile:
        # login via SMS: identità composita + parametri nel BODY (query VUOTA)
        params = build_params_mobile(phone, area, code, codefmt)
    else:
        params = build_params(email, code, emailfmt, codefmt)
    if secret == "h5md5":
        # vecchio schema MD5/5c7af05e/marketing, niente brackets (POST)
        import hashlib, time
        ts = int(time.time()*1000)
        S, N = "5c7af05e6fbf562842ef483ee96e06a0", "chery_legend_marketing"
        sig = hashlib.md5(f"{S}{N}{TOKEN_PATH}{ts}".encode()).hexdigest()
        H = A.headers_post(TOKEN_PATH, **_dept(area))  # base
        H.update({"nonce": N, "timestamp": str(ts), "signature": sig})
    else:
        H = A.headers_post(TOKEN_PATH, secret=sec, **_dept(area))
    # ⚠️ mobile → BODY (data=), email → QUERY (params=). È la differenza che fa coniare il
    # token mobile (verificato dal vivo 2026-08-02: la forma in query dà "codice non valido").
    if is_mobile:
        r = requests.post(A.BFF + "/auth/oauth2/token", data=params, headers=H, timeout=20)
    else:
        r = requests.post(A.BFF + "/auth/oauth2/token", params=params, headers=H, timeout=20)
    try: j = r.json()
    except Exception: j = {"_raw": r.text[:300]}
    tok = j.get("access_token") or (j.get("data") or {}).get("access_token")
    if verbose:
        # LOG per il debug/supporto: la FORMA del tentativo + stato/chiave server. L'utente può
        # incollare questo blocco in una issue PUBBLICA → non deve contenere né credenziali né
        # dati personali: il codice OTP si registra solo per lunghezza e il numero mascherato
        # (le ultime 4 cifre bastano a riconoscere «è il mio numero», non a identificarlo).
        # I TOKEN sono redatti da _redact nella riga sotto.
        via = f"mobile mobile={_mask_identity(params.get('mobile'))}" if is_mobile else f"email={emailfmt}"
        print(f"[login {via} code_len={len(str(code))} code_fmt={codefmt} loc={'BODY' if is_mobile else 'QUERY'}] HTTP {r.status_code}")
        print("  resp:", json.dumps(_redact(j), ensure_ascii=False)[:400])
    return r.status_code, j, tok


def _mask_identity(mobile):
    """`APP-LOGIN@<numero>_<prefisso>` → `APP-LOGIN@***<ultime 4>_<prefisso>`: tiene la forma
    dell'identità (che è poi ciò che si sta verificando) e butta il numero. Lo stdout di questo
    script viene loggato da Home Assistant, e i log finiscono nelle issue pubbliche.

    ⚠️ Prima questa funzione, sotto le 4 cifre, restituiva la stringa **in chiaro**: una
    mascheratura che si arrende sui casi limite non è una mascheratura. La regola unica sta in
    `core/mask.py` e non ha rami che lascino passare l'originale.
    ⚠️ Nessun numero per esteso nei commenti: `check_secrets.sh` li segnala tutti."""
    return mask.identita_mobile(mobile)


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
    phone = os.environ.get("OMODA_PHONE", "")
    area = os.environ.get("OMODA_AREA", "39")
    # login via SMS: serve (telefono + codice); via email: (email + codice)
    if not code or not (phone or email):
        # ⚠️ Sentinella e motivo anche qui. Prima questo ramo stampava il solo testo d'uso, e
        # `session._riga_utile` — che cerca l'ultima riga significativa — mostrava all'utente
        # una frase a caso di quel testo come «motivo del rifiuto del codice». È lo stesso
        # difetto già corretto nel gemello `login_omoda.py`, che qui era rimasto.
        print(__doc__)
        print("MOTIVO: manca il codice OTP oppure l'identità (numero o e-mail)")
        print("RESULT: FAIL")
        sys.exit(1)
    secret  = sys.argv[3] if len(sys.argv) > 3 else "prod"
    emailfmt= sys.argv[4] if len(sys.argv) > 4 else "module"
    codefmt = sys.argv[5] if len(sys.argv) > 5 else "plain"
    sc, j, tok = call(email, code, secret, emailfmt, codefmt, phone=phone, area=area)
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
