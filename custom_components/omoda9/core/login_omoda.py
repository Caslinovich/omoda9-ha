"""
login_omoda.py — login completo OMODA 'legend' via codice EMAIL.

Uso in 2 fasi (il codice email scade in pochi minuti):
  FASE 1:  python3 login_omoda.py invia <email>
           -> risolve il captcha e fa partire il codice via email. Stampa l'esito.
  FASE 2:  python3 login_omoda.py token <email> <codice>
           -> prova le combinazioni note di oauth2/token, salva token.json,
              poi tenta lo Stadio 2 (TSP + lista veicoli).
"""
import os, sys, time, json, hashlib, requests
# Questo file è eseguito COME SCRIPT in sottoprocesso (session.request_otp), dove non
# esiste un pacchetto padre → si tenta l'import relativo e si ripiega su quello nudo.
try:
    from . import captcha_solver as C
    from . import omoda
except ImportError:
    import captcha_solver as C
    import omoda

BFF = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # regione (default EU)
SECRET = "5c7af05e6fbf562842ef483ee96e06a0"
NONCE = "chery_legend_marketing"
def _md5(s): return hashlib.md5(s.encode()).hexdigest()

def _hdr_form(path):
    ts = int(time.time() * 1000)
    return {"Authorization": omoda.APP_BASIC,
            "TENANT-CODE": omoda.TENANT_CODE, "TENANT-ID": omoda.TENANT_CODE,
            "tenantCode": omoda.TENANT_CODE, "tenantID": omoda.TENANT_CODE, "tenant": omoda.TENANT_CODE,
            "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
            "appversion": omoda.APP_VERSION, "User-Agent": "okhttp/4.9.0", "Accept-Language": "it-IT",
            "nonce": NONCE, "timestamp": str(ts), "url": path,
            "signature": _md5(f"{SECRET}{NONCE}{path}{ts}"),
            "Content-Type": "application/x-www-form-urlencoded"}

def invia(email):
    """Invia il codice OTP via email. Ritorna True/False (H7: l'esito è il valore di
    ritorno; il __main__ stampa la sentinella `RESULT: OK/FAIL` per session.request_otp)."""
    print("Risolvo il captcha…")
    cv = C.risolvi()
    if not cv:
        print("❌ captcha non risolto, riprova."); return False
    path = "/marketing/v2/app/code/sendMailCode"
    r = requests.post(BFF + path,
                      data={"email": email, "module": "APP-LOGIN", "captchaVerification": cv},
                      headers=_hdr_form(path), timeout=15)
    try: j = r.json()
    except Exception: j = {"_t": r.text[:200]}
    print(f"sendMailCode -> HTTP {r.status_code} key={j.get('key')} msg={j.get('msg')} data={j.get('data')}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Codice inviato all'email. Ora: python3 login_omoda.py token <email> <codice>")
        return True
    if j.get("key") == "email.not.exists":
        print("⚠️  Email non riconosciuta come account. Verifica l'indirizzo registrato nell'app.")
    return False

def invia_sms(mobile, area="39"):
    mobile = mobile.lstrip("+").replace(" ", "")
    print("Risolvo il captcha…")
    cv = C.risolvi()
    if not cv:
        print("❌ captcha non risolto, riprova."); return False
    path = "/marketing/v2/app/code/sendSmsCode"
    r = requests.post(BFF + path,
                      data={"mobile": mobile, "areaCode": area, "module": "APP-LOGIN", "captchaVerification": cv},
                      headers=_hdr_form(path), timeout=15)
    try: j = r.json()
    except Exception: j = {"_t": r.text[:200]}
    print(f"sendSmsCode -> HTTP {r.status_code} {j}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Codice inviato via SMS. Ora: python3 login_omoda.py token-sms <mobile> <codice>")
        return True
    return False

# combinazioni oauth2/token da provare (codeId NON serve)
def _combos(email, code):
    # primo: replica ESATTA del builder app email-login (grant_type=email, scope=server, loginType=email, loginAction=1)
    return [
        {"grant_type": "email", "scope": "server", "loginType": "email", "loginAction": "1", "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "email", "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "email", "scope": "server", "loginType": "email", "loginAction": "1", "username": email, "email": email, "code": code, "needDecode": "0"},
        {"grant_type": "password", "loginType": "email", "loginAction": "1", "email": email, "code": code, "needDecode": "0"},
    ]

def _combos_sms(mobile, code, area="39"):
    mobile = mobile.lstrip("+").replace(" ", "")
    return [
        {"grant_type": "mobile", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
        {"grant_type": "mobile", "mobile": f"{area}{mobile}", "code": code, "needDecode": "0"},
        {"grant_type": "password", "loginType": "mobile", "loginAction": "1", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
        {"grant_type": "sms", "mobile": mobile, "code": code, "areaCode": area, "needDecode": "0"},
    ]

def _token_headers(path, params):
    """Parametri in QUERY + firma (keys + [valori]) — formato del gateway."""
    keys = list(params.keys())
    vals_csv = ",".join(str(params[k]) for k in keys)
    ts = int(time.time() * 1000)
    return {"Authorization": omoda.APP_BASIC, "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "okhttp/4.9.0",
            "TENANT-CODE": omoda.TENANT_CODE, "TENANT-ID": omoda.TENANT_CODE,
            "tenantCode": omoda.TENANT_CODE, "tenantID": omoda.TENANT_CODE, "tenant": omoda.TENANT_CODE,
            "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
            "appversion": omoda.APP_VERSION, "Accept-Language": "it-IT",
            "nonce": NONCE, "timestamp": str(ts), "url": path, "keys": ",".join(keys),
            "signature": _md5(f"{SECRET}{NONCE}{path}{ts}[{vals_csv}]")}

def token(email, code, sms=False, area="39"):
    win = None
    combos = _combos_sms(email, code, area) if sms else _combos(email, code)
    for params in combos:
        H = _token_headers("/auth/oauth2/token", params)
        r = requests.post(f"{BFF}/auth/oauth2/token", params=params, headers=H, timeout=20)
        try: j = r.json()
        except Exception: j = {"_t": r.text[:150]}
        tok = j.get("access_token") or (j.get("data") or {}).get("access_token")
        print(f"  {params.get('grant_type')}/{params.get('loginType','-')} -> HTTP {r.status_code} "
              f"{'OK!' if tok else (j.get('msg') or j.get('error_description') or j.get('error') or j.get('key'))}")
        if tok: win = j; break
        time.sleep(0.5)
    if not win:
        print("❌ nessuna combinazione ha funzionato (codice scaduto/sbagliato o campi diversi)."); return False
    with open("token.json", "w") as fh:
        json.dump(win, fh, indent=2, ensure_ascii=False)
    os.chmod("token.json", 0o600)   # il token è una credenziale: leggibile solo dal proprietario
    tok = win.get("access_token") or (win.get("data") or {}).get("access_token")
    # LOW: non stampare il token (lo stdout può finire nei log) — solo conferma
    print("\n✅ LOGIN OK — token salvato in token.json.")
    # Stadio 2
    HB = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "User-Agent": "okhttp/4.9.0",
          "tenant": omoda.TENANT_CODE, "channelId": omoda.CHANNEL_ID, "countryId": omoda.COUNTRY_ID,
          "appversion": omoda.APP_VERSION}
    for nome, ep in [("TSP login", "tsp/v1/app/auth/login"), ("getTuserId", "tsp/v1/app/auth/getTuserId"),
                     ("veicoli", "tsp/v1/app/vmc/queryList")]:
        try:
            r = requests.post(f"{BFF}/{ep}", json={}, headers=HB, timeout=25)
            print(f"\n=== {nome} [HTTP {r.status_code}] ===\n{r.text[:1200]}")
        except requests.RequestException as e:
            print(f"\n=== {nome}: ERRORE RETE {e} ===")
    return True

def _emit_result(ok):
    """H7: sentinella stabile + exit code per i chiamanti (session.py)."""
    print("RESULT: OK" if ok else "RESULT: FAIL")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    a = sys.argv
    # P1-4: l'email può arrivare dall'ambiente (OMODA_EMAIL) invece che da argv, così non
    # finisce nella riga di comando visibile in `ps`. argv resta supportato per l'uso a mano.
    _env_email = os.environ.get("OMODA_EMAIL", "")

    def _email(idx):
        return a[idx] if len(a) > idx else _env_email

    if len(a) >= 2 and a[1] == "invia" and _email(2):
        _emit_result(invia(_email(2)))
    elif len(a) >= 2 and a[1] == "invia-sms" and _email(2):
        _emit_result(invia_sms(_email(2), a[3] if len(a) > 3 else "39"))
    elif len(a) >= 4 and a[1] == "token":
        _emit_result(token(a[2], a[3]))
    elif len(a) >= 4 and a[1] == "token-sms":
        _emit_result(token(a[2], a[3], sms=True))
    else:
        print(__doc__)
