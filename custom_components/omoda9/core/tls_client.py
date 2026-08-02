#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tls_client.py — client HTTP per l'UNICO endpoint dietro il WAF Aliyun (`sendSmsCode`).

PERCHÉ ESISTE
-------------
Il WAF davanti a `sendSmsCode` non guarda le intestazioni: filtra sull'**impronta TLS**
del client. `requests` con le impostazioni di serie di Python viene servito con la pagina
anti-bot (`aliyun_waf_aa`); basta però presentare un ClientHello diverso — **la lista dei
cifrari**, che è l'unica leva che `requests` concede — perché la richiesta passi e arrivi al
server applicativo. Verificato dal
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
import time

# Sotto questa soglia un tentativo non fa in tempo nemmeno a completare la stretta di mano
# TLS: meglio rinunciare al gradino che sprecare una richiesta del budget dell'endpoint.
_TEMPO_MINIMO = 6.0

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

    def __init__(self, stato, testo, client, bloccato_ip=False, errore_rete=False):
        self.stato = stato
        self.testo = testo or ""
        self.client = client
        self.bloccato_ip = bloccato_ip
        # Nessun client è riuscito a PARLARE col server (rete giù, DNS, TLS). È una causa a
        # sé: dirla «respinto dal filtro anti-bot» manda l'utente a installare pacchetti da
        # una rete che non c'è.
        self.errore_rete = errore_rete

    @property
    def passato(self) -> bool:
        return self.testo.strip().startswith("{")

    def json(self):
        import json
        try:
            return json.loads(self.testo)
        except Exception:
            return {}


# Stati che significano «rallenta e riprova più tardi», non «ti ho riconosciuto come bot».
# 405 è quello osservato dal vivo su questo endpoint; 429 e 503 sono le forme standard della
# stessa cosa e non c'è ragione di aspettare di incontrarle per gestirle.
STATI_DI_ATTESA = (405, 429, 503)


def _e_ban_ip(stato, testo) -> bool:
    """Stato che dice «troppe richieste, aspetta» con corpo non-JSON.

    Va distinto dal blocco d'impronta (che arriva con HTTP 200 e la pagina `aliyun_waf_aa`):
    contro questo cambiare client non serve — vale per l'indirizzo IP, non per il client — e
    ogni tentativo in più allunga il blocco. Il corpo JSON esclude il caso: una risposta
    applicativa con quello stato viene dal server vero, quindi il WAF è già stato superato."""
    return stato in STATI_DI_ATTESA and not (testo or "").strip().startswith("{")


# ---------------------------------------------------------------- i singoli client

def _contesto_tls():
    """SSLContext con la lista dei cifrari scelta da noi: è ciò che cambia l'impronta.

    ⚠️ NON provare a impostare anche l'ALPN qui: non arriverebbe mai sul filo. `urllib3`
    esegue `context.set_alpn_protocols(["http/1.1"])` **incondizionatamente** dentro
    `ssl_wrap_socket`, sovrascrivendo qualunque cosa si sia messa (verificato leggendo il
    sorgente di urllib3 2.7 e catturando il ClientHello: 15 suite, `alpn=['http/1.1']`).
    Una versione precedente di questo file offriva `["h2","http/1.1"]` e ne aveva ricavato
    due gradini di scala che producevano **byte identici** — cioè un tentativo sprecato su un
    endpoint che di tentativi ne concede tre.

    ⚠️ I nomi di cifrario sconosciuti a una build di OpenSSL vengono scartati **in silenzio**
    (misurato: `set_ciphers("BOGUS:ECDHE-RSA-AES128-GCM-SHA256")` non solleva). Su questa
    macchina `DES-CBC3-SHA` non esiste più e le suite offerte sono 15 invece di 16. L'impronta
    dipende quindi anche dalla build di OpenSSL della distribuzione, non solo da questa lista:
    è il motivo per cui sotto c'è comunque una scala di ripieghi."""
    try:
        from urllib3.util.ssl_ import create_urllib3_context
        return create_urllib3_context(ciphers=CIFRARI)
    except Exception:                                   # urllib3 diverso dal previsto
        import ssl
        ctx = ssl.create_default_context()
        ctx.set_ciphers(CIFRARI)
        return ctx


def _post_requests_tls(url, data, headers, timeout):
    """`requests` con contesto TLS ritoccato — nessuna dipendenza in più, ovunque."""
    import requests
    from requests.adapters import HTTPAdapter

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *a, **k):
            k["ssl_context"] = _contesto_tls()
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
    già adottata in session.py per email e OTP.

    ⚠️⚠️ IL RITORNO A CAPO È IL CARATTERE PERICOLOSO, non le virgolette. Il file di
    configurazione di `curl` è **una opzione per riga**: un valore che contenga `\\n` chiude la
    riga e ciò che segue viene letto come una OPZIONE NUOVA. Con `output`, `upload-file`,
    `proxy` o `cert` si scrive, si legge o si spedisce fuori un file qualsiasi del sistema —
    per esempio il token dell'auto. Non è teorico: le intestazioni includono `channelId`,
    `countryId` e `tenantCode`, che arrivano da **campi di testo liberi del config flow**.
    `curl` interpreta `\\n`, `\\r`, `\\t` dentro le virgolette come sequenze di escape, quindi
    convertirli è insieme sicuro e fedele: il valore arriva a destinazione com'era."""
    def _q(v):
        return '"' + (str(v).replace("\\", "\\\\").replace('"', '\\"')
                      .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")) + '"'

    def _intestazione(k, v):
        """⚠️ Nelle INTESTAZIONI il ritorno a capo va TOLTO, non convertito.

        Schermarlo con `\\n` mette al sicuro il file di configurazione, ma `curl` riespande la
        sequenza dentro il valore dell'intestazione e la scrive sul filo: l'iniezione si sposta
        dal file al protocollo HTTP, e chi controlla `channelId` (campo di testo libero del
        config flow) può aggiungere intestazioni a piacere. In HTTP un'intestazione non può
        contenere ritorni a capo: qui si buttano, non si tenta di rappresentarli. `requests`
        fa lo stesso, sollevando `InvalidHeader` — così i due gradini della scala si comportano
        allo stesso modo invece di divergere in silenzio."""
        pulito = "".join(ch for ch in str(v) if ch not in "\r\n")
        return f"header = {_q(f'{k}: {pulito}')}"

    righe = ["silent", "show-error", "request = POST", f"url = {_q(url)}",
             f"max-time = {int(timeout)}", 'write-out = "\\n<<<STATO:%{http_code}"']
    righe += [_intestazione(k, v) for k, v in headers.items()]
    # Nel CORPO invece il ritorno a capo è legittimo: `--data-urlencode` lo codifica in `%0A`,
    # quindi non può rompere niente e il valore arriva identico (verificato).
    righe += [f"data-urlencode = {_q(f'{k}={v}')}" for k, v in data.items()]

    # `-q` PRIMA di tutto: senza, `curl` legge comunque `~/.curlrc`, dove un `proxy`,
    # un `insecure` o un `ciphers` altererebbero in silenzio proprio la cosa che questo
    # gradino esiste per controllare — l'impronta TLS — e potrebbero dirottare una richiesta
    # che contiene il numero di telefono. `--config -` non lo sopprime.
    # `errors="replace"`: la pagina di blocco di un WAF cinese arriva spesso in GBK, e senza
    # questo la decodifica alzava `UnicodeDecodeError` proprio nel caso in cui questo gradino
    # serve. Il corpo qui si guarda solo per capire se è JSON: una sostituzione non fa danno.
    p = subprocess.run(["curl", "-q", "--config", "-"], input="\n".join(righe) + "\n",
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout + 10)
    # ⚠️ Il codice di uscita va guardato PRIMA del corpo: `curl` scrive comunque il `write-out`,
    # quindi una connessione rifiutata, un DNS che non risolve o una stretta di mano TLS fallita
    # producono un onestissimo `(0, "")` — che più a valle diventava «respinto dal filtro
    # anti-bot». Sollevare qui fa sì che la scala lo tratti per quello che è: un client che non
    # ha parlato con nessuno, non un client respinto.
    if p.returncode != 0:
        raise RuntimeError(f"curl rc={p.returncode}: {(p.stderr or '').strip()[:120]}")
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
# nome → funzione. ⚠️ Ogni voce in più è una RICHIESTA in più su un endpoint che ne concede
# tre prima di bloccare l'IP: la scala va tenuta corta e ogni gradino deve avere un'impronta
# davvero diversa dagli altri, altrimenti spende il budget senza aggiungere possibilità.
CLIENT = {
    "requests+tls": _post_requests_tls,   # cifrari ritoccati — è la strada verificata
    "curl":         _post_curl,           # impronta completamente diversa, nessuna dipendenza
    "curl_cffi":    _post_curl_cffi,      # solo se già presente: di solito non costa nulla
    "requests":     _post_requests_nudo,  # ultima spiaggia, se il WAF cambiasse criterio
}
SCALA = ["requests+tls", "curl", "curl_cffi", "requests"]


# ---------------------------------------------------------------- memoria del vincitore

def _file_memoria() -> str | None:
    """File accanto al token dove si ricorda il client che ha funzionato.

    Contiene un solo nome di client: nessun dato personale, nessuna credenziale."""
    tp = os.environ.get("OMODA_TOKEN_PATH", "")
    if not tp:
        return None
    # Se il percorso indica una CARTELLA, `dirname` risalirebbe al suo genitore: con
    # `OMODA_TOKEN_PATH=/config` si finiva a scrivere in `/`, cioè nella radice del
    # filesystem del container.
    tp = os.path.abspath(tp)
    d = tp if os.path.isdir(tp) else (os.path.dirname(tp) or ".")
    if not os.path.isdir(d):
        return None
    return os.path.join(d, "omoda9_tls_client.txt")


def _leggi_memoria() -> str | None:
    f = _file_memoria()
    if not f or not os.path.isfile(f):
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            nome = fh.read().strip()
        return nome if nome in CLIENT else None
    except Exception:
        # ⚠️ `except OSError` NON bastava: un file non testuale fa alzare `UnicodeDecodeError`,
        # che è un `ValueError` e risaliva fuori da `post_waf` — contro il contratto dichiarato
        # («ritorna sempre un Esito, non solleva»). Il sottoprocesso moriva con un traceback,
        # senza sentinella, e all'utente arrivava l'ultima riga del traceback come «motivo».
        # Questo file è un'ottimizzazione: qualunque cosa contenga, si riparte dalla scala.
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
    risposte = 0            # quanti client hanno ottenuto una risposta HTTP, quale che sia
    ordine = _ordine()
    # ⚠️ `timeout` è il budget COMPLESSIVO, non quello di ogni gradino. Dandolo a ciascuno, una
    # scala di client tutti in timeout costava la somma — misurato: 100 s su cinque gradini,
    # mentre il sottoprocesso di login ne ha 120 in tutto e il captcha ne ha già spesi fino a
    # 30. L'invio moriva per timeout senza nemmeno riuscire a dire perché.
    scadenza = time.monotonic() + timeout
    for i, nome in enumerate(ordine):
        resto = scadenza - time.monotonic()
        if resto <= 0:
            log(f"[TLS] tempo esaurito: {len(ordine) - i} client non provati")
            break
        # Il tempo che resta diviso i client ancora da provare, ma mai meno del minimo utile —
        # e mai più di quanto resta davvero. Il `min` serve a non rendere inservibile un budget
        # complessivo piccolo: meglio un tentativo con poco tempo che nessun tentativo.
        quota = max(min(_TEMPO_MINIMO, resto), resto / (len(ordine) - i))
        try:
            stato, testo = CLIENT[nome](url, data, headers, quota)
        except ImportError:
            log(f"[TLS] {nome}: non installato, salto")
            continue
        except FileNotFoundError:
            log(f"[TLS] {nome}: eseguibile assente, salto")
            continue
        except Exception as e:                  # rete, TLS, timeout: si prova il prossimo
            log(f"[TLS] {nome}: {type(e).__name__}: {str(e)[:90]}")
            continue

        risposte += 1
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
    if not risposte:
        # Nemmeno un client ha ottenuto una risposta: non è il filtro anti-bot, è la rete.
        return Esito(0, "", ultimo.client, errore_rete=True)
    return ultimo


def curl_cffi_presente() -> bool:
    """C'è già `curl_cffi`? Serve a session.py per decidere se vale la pena installarlo
    come ultima spiaggia, quando tutta la scala portatile è stata respinta."""
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False
