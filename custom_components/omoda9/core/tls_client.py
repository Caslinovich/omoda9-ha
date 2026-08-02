#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tls_client.py — client HTTP per l'UNICO endpoint dietro il WAF Aliyun (`sendSmsCode`).

PERCHÉ ESISTE
-------------
Il WAF davanti a `sendSmsCode` non guarda le intestazioni: filtra sull'**impronta TLS**
del client. `requests` con le impostazioni di serie di Python viene servito con la pagina
anti-bot (`aliyun_waf_aa`); basta però presentare un ClientHello diverso — altra lista di
cifrari, ALPN h2 — perché la richiesta passi e arrivi al server applicativo. Verificato dal
vivo il 2026-08-02 dal container Home Assistant, confrontando sei client sullo stesso
endpoint: `requests` nudo bloccato, `requests` con contesto TLS ritoccato e `curl` di
sistema passati (risposta JSON del server). Tutti gli altri endpoint del BFF (captcha,
`sendMailCode`, `oauth2/token`, TSP) NON sono dietro il WAF e restano su `requests` nudo.

PERCHÉ NON SI DIPENDE DA UNA LIBRERIA BINARIA
---------------------------------------------
`curl_cffi` **funziona** (riverificato il 2026-08-02: supera il WAF), e resta in fondo alla
scala. Non è però una buona fondazione, perché non è nei `requirements` del manifest — e non
può esserci: una requirement che non si installa fa sollevare `RequirementsNotFound` e
**impedisce il caricamento dell'INTERA integrazione**, anche a chi accede via e-mail e non
invierà mai un SMS. Restava quindi l'installazione a richiesta dal config flow, che si porta
dietro una catena di guai misurati:

  * il pacchetto viene scritto in `site.getusersitepackages()` — dentro il container HA è
    `/root/.local/...`, che **non è fra i volumi montati**: ogni `ha core update` ricrea il
    container e lo cancella. Nessuno lo reinstalla all'avvio, perché non è nel manifest; il
    guasto si scopre mesi dopo, quando la sessione scade e serve un OTP;
  * un fallimento anche solo momentaneo (rete assente in quell'istante) entra in
    `install_failure_history` e da lì in poi HA rifiuta **all'istante, senza ritentare**, fino
    al riavvio di Home Assistant;
  * su un'installazione senza venv il pacchetto finisce in `<config>/deps`, che Home Assistant
    aggiunge al proprio `sys.path` ma **non** a `PYTHONPATH`: il sottoprocesso di login non lo
    vedrebbe comunque, e l'utente leggerebbe «installa curl_cffi» con curl_cffi già installato;
  * si tira dietro copie proprie di `cffi` e `certifi` che finiscono davanti a quelle di Home
    Assistant, ~12 MB da scaricare e ~38 MB su disco.

Qui invece la stessa impronta TLS si ottiene con `ssl` della libreria standard, sopra il
`requests` che è **già** nel manifest: niente da compilare, niente da scaricare, nessuna
differenza fra un Raspberry e un PC, e nulla che un aggiornamento di Home Assistant possa
portarsi via. `curl_cffi` diventa quello che dovrebbe essere: un ripiego, se c'è.

LA SCALA DEI TENTATIVI
----------------------
Si prova una scala di client e si tiene il primo che supera il WAF. Serve perché il criterio
del WAF può cambiare: se un giorno l'impronta ritoccata smettesse di passare, il ripiego
successivo copre senza dover rilasciare una versione nuova. Misurato il 2026-08-02, in finestre
separate per non falsarsi a vicenda: `requests` di serie **respinto** (pagina `aliyun_waf_aa`),
`requests` con cifrari e ALPN ritoccati **passa**, `curl` di sistema **passa**, `curl_cffi`
**passa**. Che passi anche il `curl` di sistema, linkato a OpenSSL, dice fra l'altro che il
discriminante NON è «BoringSSL contro OpenSSL» come si era ipotizzato all'inizio.

⚠️ TENTATIVI CONTATI, non illimitati. Nella stessa prova l'endpoint ha iniziato a rispondere
**HTTP 405** a *tutti* i client dopo tre richieste ravvicinate, e ha continuato per **oltre
mezz'ora**: è un blocco temporaneo sull'IP, non sul client. Perciò (a) il 405 interrompe subito
la scala — cambiare client non serve a nulla e allunga il blocco — e viene riportato come causa
distinta, così all'utente si può dire «aspetta» invece di «è rotto»; (b) il client che ha
funzionato viene ricordato su file, così i login successivi partono da quello e costano UNA
richiesta sola.
"""
from __future__ import annotations

import os
import subprocess
import urllib.parse

# Lista di cifrari in ordine "stile BoringSSL": è ciò che cambia l'impronta rispetto al
# default di Python. Presa dal client che nella prova ha superato il WAF.
CIFRARI = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA:DES-CBC3-SHA"
)


class Esito:
    """Risultato di una richiesta all'endpoint protetto.

    `passato` distingue «il WAF mi ha fatto entrare» (risposta JSON del server, che poi può
    benissimo contenere un errore applicativo) da «mi ha respinto» (pagina HTML). È questa
    la discriminante da usare per decidere se cambiare client: lo stato HTTP no, perché il
    WAF risponde 200 anche quando blocca."""

    def __init__(self, stato, testo, client, bloccato_ip=False):
        self.stato = stato
        self.testo = testo or ""
        self.client = client
        self.bloccato_ip = bloccato_ip

    @property
    def passato(self) -> bool:
        return self.testo.strip().startswith("{")

    def json(self):
        import json
        try:
            return json.loads(self.testo)
        except Exception:
            return {}


def _e_ban_ip(stato, testo) -> bool:
    """HTTP 405 con corpo non-JSON = blocco temporaneo sull'IP per troppe richieste.

    Va distinto dal blocco d'impronta (che arriva con HTTP 200 e la pagina `aliyun_waf_aa`):
    contro il ban IP cambiare client non serve, si può solo aspettare."""
    return stato == 405 and not (testo or "").strip().startswith("{")


# ---------------------------------------------------------------- i singoli client

def _contesto_tls(alpn):
    """SSLContext con cifrari e ALPN scelti da noi (è ciò che cambia l'impronta)."""
    try:
        from urllib3.util.ssl_ import create_urllib3_context
        ctx = create_urllib3_context(ciphers=CIFRARI)
    except Exception:                                   # urllib3 diverso dal previsto
        import ssl
        ctx = ssl.create_default_context()
        ctx.set_ciphers(CIFRARI)
    if alpn:
        try:
            ctx.set_alpn_protocols(alpn)
        except Exception:
            pass
    return ctx


def _post_requests_tls(url, data, headers, timeout, alpn):
    """`requests` con contesto TLS ritoccato — nessuna dipendenza in più, ovunque."""
    import requests
    from requests.adapters import HTTPAdapter

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *a, **k):
            k["ssl_context"] = _contesto_tls(alpn)
            return super().init_poolmanager(*a, **k)

    s = requests.Session()
    s.mount("https://", _Adapter())
    try:
        r = s.post(url, data=data, headers=headers, timeout=timeout)
        return r.status_code, r.text
    finally:
        s.close()


def _post_curl(url, data, headers, timeout):
    """`curl` di sistema (c'è nell'immagine Home Assistant).

    ⚠️ Tutto passa da **stdin** con `--config -`, niente in argv: il corpo contiene il
    numero di telefono e il token del captcha, e la riga di comando di un processo è
    leggibile da chiunque sulla macchina (`ps`, `/proc/<pid>/cmdline`). È la stessa cautela
    già adottata in session.py per email e OTP."""
    def _q(v):
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    righe = ["silent", "show-error", "request = POST", f"url = {_q(url)}",
             f"max-time = {int(timeout)}", 'write-out = "\\n<<<STATO:%{http_code}"']
    righe += [f"header = {_q(f'{k}: {v}')}" for k, v in headers.items()]
    righe += [f"data-urlencode = {_q(f'{k}={v}')}" for k, v in data.items()]

    p = subprocess.run(["curl", "--config", "-"], input="\n".join(righe) + "\n",
                       capture_output=True, text=True, timeout=timeout + 10)
    out = p.stdout or ""
    stato, sep, coda = out.rpartition("\n<<<STATO:")
    if not sep:
        raise RuntimeError(f"curl senza esito (rc={p.returncode}): {(p.stderr or '')[:120]}")
    try:
        return int(coda.strip()), stato
    except ValueError:
        raise RuntimeError(f"curl: stato illeggibile {coda[:40]!r}")


def _post_curl_cffi(url, data, headers, timeout):
    """`curl_cffi` — usato SOLO se già presente. Non è più una requirement del manifest."""
    from curl_cffi import requests as _cffi          # noqa: PLC0415  (import volutamente pigro)
    r = _cffi.post(url, data=data, headers=headers, timeout=timeout)
    return r.status_code, r.text


def _post_requests_nudo(url, data, headers, timeout):
    """`requests` senza ritocchi: nella prova viene bloccato, ma se il WAF cambiasse
    criterio sarebbe il client più semplice a funzionare. Costa nulla tenerlo in fondo."""
    import requests
    r = requests.post(url, data=data, headers=headers, timeout=timeout)
    return r.status_code, r.text


# nome → funzione. L'ordine è quello della scala; il primo è quello verificato sul campo.
CLIENT = {
    "requests+tls":     lambda u, d, h, t: _post_requests_tls(u, d, h, t, ["h2", "http/1.1"]),
    "requests+cifrari": lambda u, d, h, t: _post_requests_tls(u, d, h, t, None),
    "curl":             _post_curl,
    "curl_cffi":        _post_curl_cffi,
    "requests":         _post_requests_nudo,
}
SCALA = ["requests+tls", "requests+cifrari", "curl", "curl_cffi", "requests"]


# ---------------------------------------------------------------- memoria del vincitore

def _file_memoria() -> str | None:
    """File accanto al token dove si ricorda il client che ha funzionato.

    Contiene un solo nome di client: nessun dato personale, nessuna credenziale."""
    tp = os.environ.get("OMODA_TOKEN_PATH", "")
    if not tp:
        return None
    d = os.path.dirname(os.path.abspath(tp)) or "."
    return os.path.join(d, "omoda9_tls_client.txt")


def _leggi_memoria() -> str | None:
    f = _file_memoria()
    if not f or not os.path.isfile(f):
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            nome = fh.read().strip()
        return nome if nome in CLIENT else None
    except OSError:
        return None


def _scrivi_memoria(nome: str) -> None:
    f = _file_memoria()
    if not f:
        return
    try:
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(nome)
    except OSError:
        pass                                    # è solo un'ottimizzazione: mai bloccante


def _ordine() -> list[str]:
    """Scala dei tentativi, col vincitore ricordato in testa.

    `OMODA_TLS_CLIENT` forza un client solo (diagnostica: isola un client senza toccare
    il codice, e senza consumare tentativi con gli altri)."""
    forzato = os.environ.get("OMODA_TLS_CLIENT", "").strip()
    if forzato in CLIENT:
        return [forzato]
    ordine = list(SCALA)
    memo = _leggi_memoria()
    if memo:
        ordine.remove(memo)
        ordine.insert(0, memo)
    return ordine


# ---------------------------------------------------------------- API pubblica

def post_waf(url, data, headers, timeout=20, log=lambda m: None) -> Esito:
    """POST all'endpoint protetto, scendendo la scala dei client fino al primo che passa.

    Ritorna sempre un `Esito` (non solleva): `passato` dice se il WAF ha fatto entrare,
    `bloccato_ip` se ci si è imbattuti nel blocco temporaneo per troppe richieste."""
    ultimo = Esito(0, "", "nessuno")
    for nome in _ordine():
        try:
            stato, testo = CLIENT[nome](url, data, headers, timeout)
        except ImportError:
            log(f"[TLS] {nome}: non installato, salto")
            continue
        except FileNotFoundError:
            log(f"[TLS] {nome}: eseguibile assente, salto")
            continue
        except Exception as e:                  # rete, TLS, timeout: si prova il prossimo
            log(f"[TLS] {nome}: {type(e).__name__}: {str(e)[:90]}")
            continue

        esito = Esito(stato, testo, nome, bloccato_ip=_e_ban_ip(stato, testo))
        if esito.passato:
            log(f"[TLS] {nome}: ✅ superato il WAF (HTTP {stato})")
            _scrivi_memoria(nome)
            return esito
        if esito.bloccato_ip:
            # Ban sull'IP: vale per tutti i client, insistere allunga solo il blocco.
            log(f"[TLS] {nome}: ⛔ HTTP 405 — troppe richieste ravvicinate, mi fermo qui")
            return esito
        log(f"[TLS] {nome}: ❌ respinto dal WAF (HTTP {stato})")
        ultimo = esito
    return ultimo


def curl_cffi_presente() -> bool:
    """C'è già `curl_cffi`? Serve a session.py per decidere se vale la pena installarlo
    come ultima spiaggia, quando tutta la scala portatile è stata respinta."""
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False
