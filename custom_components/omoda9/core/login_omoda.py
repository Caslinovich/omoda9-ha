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
    from . import mask
    from . import tls_client
except ImportError:
    import captcha_solver as C
    import omoda
    import mask
    import tls_client

# Sentinella STABILE per la causa di un fallimento, letta da `core/session.py`. Nasce da un
# difetto concreto: `_riga_utile` prendeva l'ultima riga significativa dello stdout, ma la
# causa vera veniva stampata per PRIMA e seguita da righe di spiegazione — all'utente arrivava
# quindi la coda di una frase («…pip install curl_cffi)») invece del motivo. Con un marcatore
# esplicito la riga giusta si riconosce sempre, e resta stabile anche se i testi cambiano.
MOTIVO = "MOTIVO:"


def _motivo(testo):
    """Dichiara la causa del fallimento in modo che `session.py` la ritrovi."""
    print(f"{MOTIVO} {testo}")

BFF = os.environ.get("OMODA_BFF", "https://legend-oj.omodaauto.nl/api")   # regione (default EU)
SECRET = "5c7af05e6fbf562842ef483ee96e06a0"
NONCE = "chery_legend_marketing"
def _md5(s): return hashlib.md5(s.encode()).hexdigest()

# L'invio SMS (`sendSmsCode`) è l'UNICO endpoint dietro il WAF Aliyun, che filtra
# sull'impronta TLS del client: `requests` con le impostazioni di serie viene servito con la
# pagina anti-bot. La scala di client che supera il filtro sta in `tls_client.py`, insieme alle
# misure che la giustificano; qui si usa e basta. Captcha, `sendMailCode` e `oauth2/token` NON
# sono dietro il WAF e restano su `requests` nudo.
def _sms_post(url, data, headers, timeout=20):
    """POST verso sendSmsCode, scendendo la scala dei client fino al primo che supera il WAF."""
    return tls_client.post_waf(url, data, headers, timeout=timeout, log=print)

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
        _motivo("il captcha del server non è stato risolto: riprova fra poco"); return False
    path = "/marketing/v2/app/code/sendMailCode"
    r = requests.post(BFF + path,
                      data={"email": email, "module": "APP-LOGIN", "captchaVerification": cv},
                      headers=_hdr_form(path), timeout=15)
    try: j = r.json()
    except Exception: j = {"_t": r.text[:200]}
    # Stato e CHIAVE del server, non il campo `data` per intero: è una risposta di terze parti
    # e questa riga finisce nei log che si allegano alle issue pubbliche. Il gemello SMS era
    # già stato ristretto; questo ramo era rimasto indietro.
    print(f"sendMailCode -> HTTP {r.status_code} key={j.get('key')} msg={j.get('msg')}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Codice inviato all'email. Ora: python3 login_omoda.py token <email> <codice>")
        return True
    if j.get("key") == "email.not.exists":
        _motivo("indirizzo e-mail non riconosciuto come account: controlla quello registrato "
                "nell'app ufficiale")
    else:
        _motivo(f"il server ha rifiutato la richiesta di invio (key={j.get('key')})")
    return False

def _mask(numero):
    """Ultime 4 cifre, il resto oscurato — regola unica in `core/mask.py`. Lo stdout di questo
    script viene loggato da Home Assistant e i log finiscono nelle issue pubbliche: il numero è
    un dato personale che (a differenza dell'OTP) non scade mai."""
    return mask.numero(numero)

def invia_sms(mobile, area="39"):
    mobile = mobile.lstrip("+").replace(" ", "")
    print(f"[SMS] invio codice al numero +{area} {_mask(mobile)}")
    print("Risolvo il captcha…")
    cv = C.risolvi()
    if not cv:
        _motivo("il captcha del server non è stato risolto: riprova fra poco"); return False
    path = "/marketing/v2/app/code/sendSmsCode"
    esito = _sms_post(BFF + path,
                      {"mobile": mobile, "areaCode": area, "module": "APP-LOGIN", "captchaVerification": cv},
                      _hdr_form(path), timeout=20)
    # ⚠️ TRE cause diverse, che prima finivano tutte in «probabile blocco WAF» e chiedevano
    # rimedi opposti: contro il ban sull'IP si può solo aspettare, contro il blocco d'impronta
    # serve un client diverso, e un errore applicativo non c'entra col WAF.
    if esito.errore_rete:
        _motivo("nessuna risposta dal server: controlla la connessione a internet di Home "
                "Assistant e riprova")
        return False
    if esito.bloccato_ip:
        _motivo("troppe richieste ravvicinate: il server ha bloccato temporaneamente questo "
                "indirizzo IP. Aspetta una mezz'ora e riprova, senza insistere nel frattempo.")
        return False
    if not esito.passato:
        _motivo(f"richiesta respinta dal filtro anti-bot del server (nessuno dei client TLS "
                f"disponibili è passato; ultimo tentativo: {esito.client}, HTTP {esito.stato})")
        return False
    j = esito.json()
    # NB: si stampano stato e CHIAVE del server, non il corpo della risposta: la pagina di
    # blocco di un WAF contiene di norma l'IP del client e un identificativo di sessione, e
    # questa riga finisce nel log che l'utente allega alle issue pubbliche.
    print(f"sendSmsCode -> HTTP {esito.stato} key={j.get('key')} msg={j.get('msg')}")
    if j.get("ok") or j.get("key") == "operation.successful":
        print("✅ Codice SMS inviato.")
        return True
    _motivo(f"il server ha rifiutato la richiesta di invio (key={j.get('key')})")
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
    _env_phone = os.environ.get("OMODA_PHONE", "")
    _env_area = os.environ.get("OMODA_AREA", "39")

    def _email(idx):
        return a[idx] if len(a) > idx else _env_email

    def _phone(idx):
        return a[idx] if len(a) > idx else _env_phone

    if len(a) >= 2 and a[1] == "invia" and _email(2):
        _emit_result(invia(_email(2)))
    elif len(a) >= 2 and a[1] == "invia-sms" and _phone(2):
        _emit_result(invia_sms(_phone(2), a[3] if len(a) > 3 else _env_area))
    elif len(a) >= 4 and a[1] == "token":
        _emit_result(token(a[2], a[3]))
    elif len(a) >= 4 and a[1] == "token-sms":
        # ⚠️ Il conio del token per gli account SMS NON si fa da qui. Le combinazioni che
        # `_combos_sms` prova (numero nudo, codice in chiaro, parametri in query) sono quelle
        # tentate PRIMA di sapere come funziona davvero, e il server le rifiuta tutte: la forma
        # buona — identità composita `APP-LOGIN@<num>_<area>`, codice cifrato SM4, parametri
        # nel body — è in `prova_token.build_params_mobile`, ricavata decompilando l'app e
        # confermata dal vivo. Lasciare qui un sottocomando che non può funzionare significa
        # che chi lo usa per diagnosticare conclude «il server rifiuta il mio codice».
        print("Il conio del token per gli account SMS si fa con prova_token.py")
        print("(OMODA_PHONE / OMODA_AREA / OMODA_OTP nell'ambiente).")
        _motivo("sottocomando non più supportato: usa prova_token.py per gli account SMS")
        _emit_result(False)
    else:
        # ⚠️ Anche qui la sentinella e il codice d'uscita. Prima questo ramo stampava il solo
        # testo d'uso e usciva con 0 — cioè con il codice del SUCCESSO — e ci finiva ogni
        # invocazione a cui mancasse l'identità (per esempio `invia-sms` senza `OMODA_PHONE`).
        # `session.py` non ci cascava, perché pretende rc=0 **e** `RESULT: OK`, ma all'utente
        # arrivava come «motivo del fallimento» una riga a caso del testo d'uso.
        print(__doc__)
        _motivo("comando non riconosciuto o identità mancante (numero/e-mail non passati)")
        _emit_result(False)
