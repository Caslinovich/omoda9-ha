#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session.py — salute del token Omoda + re-login OTP guidato da Home Assistant.

Il token che fa funzionare i pulsanti comando vive in token.json (wake.TOKEN_PATH).
Due modi in cui può "cadere":
  1) l'access_token scade normalmente  -> refresh() lo rinnova col refresh_token (NIENTE OTP);
  2) Rino apre l'app ufficiale          -> la sessione viene invalidata (424) e nemmeno il
                                           refresh basta -> serve un OTP nuovo.

Questo modulo espone le primitive che il ponte cabla a 3 entità HA:
  - check()         -> (ok, dettaglio)   : il token è valido? (prova un login BFF)
  - refresh()       -> bool              : rinnova l'access_token senza OTP (keep-alive)
  - request_otp()   -> bool              : invia il codice OTP alla mail (login_omoda.py invia)
  - confirm_otp(c)  -> (ok, dettaglio)   : conia il token col codice (prova_token.py)  poi ricontrolla

request_otp/confirm_otp girano login_omoda.py / prova_token.py COME SOTTOPROCESSO nella
cartella OMODA_SRC_DIR (default = questa stessa cartella `core/`, dove vivono anche
captcha_solver/omoda) col python corrente (sys.executable). Nel component HA = il python
di HA, che ha le requirements del manifest (requests/pycryptodome/numpy/pillow).

Contratto sottoprocessi (H7): login_omoda.py e prova_token.py stampano su stdout una
riga-sentinella stabile `RESULT: OK` / `RESULT: FAIL` e usano il returncode (0 ok, !=0
errore). request_otp/confirm_otp decidono l'esito su returncode + sentinella, NON su
sottostringhe localizzate (che cambierebbero con la lingua dei messaggi).
"""
import os, sys, subprocess, time, logging

HERE = os.path.dirname(os.path.abspath(__file__))
_LOGGER = logging.getLogger(__name__)

# P2-2: import relativo di pacchetto (prima: nome nudo + `sys.path.insert(HERE)`).
from . import wake  # riusa _bff_login / _refresh_token / TOKEN_PATH
from . import mask  # mascheratura unica dei dati personali nelle frasi che escono da qui

# Marcatore con cui i sottoprocessi dichiarano la CAUSA di un fallimento (login_omoda.MOTIVO).
# Duplicato qui di proposito: importare `login_omoda` da questo modulo significherebbe tirarsi
# dentro `requests` e il risolutore di captcha solo per leggere una costante di sette caratteri.
_MOTIVO = "MOTIVO:"

# P2-6: email e cartella sorgenti arrivano dal `CoreCtx` del veicolo, non più da global
# di modulo popolati da os.environ.
PYEXE     = sys.executable  # il python di Home Assistant (ha le requirements del manifest)
_TIMEOUT  = int(os.environ.get("OMODA_OTP_TIMEOUT", "120"))


# P1-1 (H7): marcatori STABILI dell'esito di check(). Il chiamante instrada il rimedio su
# questi, MAI sul testo umano (che è localizzato e può cambiare a ogni ritocco di copy).
STATUS_OK = "OK"                # login BFF riuscito col token attuale
STATUS_EXPIRED = "EXPIRED"      # token/sessione morti → serve un OTP nuovo (reauth)
STATUS_NET_ERROR = "NET_ERROR"  # errore di rete/transitorio → NON è una sessione scaduta

# Quanto a lungo il motivo dell'ultimo rinnovo resta attendibile per decidere il rimedio.
# Rinnovo e controllo sessione avvengono nello stesso giro (frazioni di secondo): un
# motivo più vecchio di così parla di un altro tentativo e va ignorato.
_MOTIVO_FRESCO_S = 60.0
# Frazione di vita del token oltre la quale si rinnova in anticipo (0.8 = a 9h36m su 12h):
# abbastanza presto da avere margine, abbastanza tardi da non sprecare rinnovi.
QUOTA_RINNOVO = 0.8


def check(ctx):
    """Ritorna (ok: bool, dettaglio: str, status: str).

    `status` è il marcatore stabile (STATUS_OK/EXPIRED/NET_ERROR): è ciò su cui il
    coordinator decide se aprire la riautenticazione. `dettaglio` è solo per l'utente.
    Distinguere EXPIRED da NET_ERROR è essenziale: un blip di rete NON deve far comparire
    la card «Riautentica» (l'utente rifarebbe un OTP inutile)."""
    try:
        ut, tu = wake._bff_login(ctx)
    except Exception as e:
        return False, f"errore rete: {type(e).__name__}", STATUS_NET_ERROR
    if ut:
        return True, "Sessione attiva ✅", STATUS_OK
    # Il login è fallito. Ma se è fallito perché il RINNOVO non è nemmeno partito (rete
    # giù, timeout, DNS), la sessione può benissimo essere ancora viva di là: dichiararla
    # scaduta farebbe comparire la card «Riautentica» e brucerebbe un OTP per niente.
    # Ci si fida del marcatore solo se è FRESCO: uno vecchio si riferisce a un altro giro.
    try:
        motivo = ctx.stato.refresh_motivo or ""
        fresco = (time.time() - (ctx.stato.refresh_ts or 0.0)) < _MOTIVO_FRESCO_S
    except Exception:  # noqa: BLE001 — contesti ridotti nei test/diagnostica
        motivo, fresco = "", False
    if fresco and motivo.startswith("rete:"):
        return False, f"rinnovo non riuscito per la rete ({motivo[5:]})", STATUS_NET_ERROR
    return (False,
            "Sessione scaduta ❌ — riautentica da Home Assistant e chiedi un codice nuovo",
            STATUS_EXPIRED)


def refresh(ctx):
    """Rinnova l'access_token col refresh_token (senza OTP). True se rinnovato."""
    try:
        return bool(wake._refresh_token(ctx))
    except Exception:
        return False


def refresh_se_prossimo_a_scadere(ctx, quota: float = QUOTA_RINNOVO) -> tuple[bool, str]:
    """Rinnovo PROATTIVO: rinnova quando l'access token ha consumato `quota` della sua
    vita, invece di aspettare che sia già morto.

    Perché non basta il rinnovo reattivo: il controllo sessione gira ogni 15 minuti, e
    quello reattivo scatta solo DOPO che il token è scaduto — cioè fino a un quarto d'ora
    in ritardo, con la finestra del refresh_token già in chiusura. Anticipando si rinnova
    sempre con la sessione ancora viva; e se il rinnovo fallisce lo si scopre mentre c'è
    ancora tempo, invece che a sessione già morta.

    Ritorna (rinnovato, motivo). `(False, "non_serve")` = non era ora, nessuna chiamata.
    Non solleva mai: è un'ottimizzazione, non deve poter rompere il keep-alive."""
    try:
        eta, durata = wake._eta_token(ctx)
        if eta < 0 or durata <= 0:
            return False, "non_determinabile"
        if eta < durata * quota:
            return False, "non_serve"
        return wake._refresh_token_detail(ctx)
    except Exception as e:  # noqa: BLE001
        return False, f"rete:{type(e).__name__}"


def _timeout() -> int:
    try:
        return int(os.environ.get("OMODA_OTP_TIMEOUT", str(_TIMEOUT)))
    except (TypeError, ValueError):
        return _TIMEOUT


def _subenv(ctx, **extra):
    """Ambiente EFFIMERO per il sottoprocesso di login.

    P1-4: email e OTP viaggiano QUI e non in argv — la riga di comando è leggibile da
    qualsiasi utente della macchina (`ps aux`, `/proc/<pid>/cmdline`), l'environment di un
    processo no. La copia è locale alla chiamata: `os.environ` del processo Home Assistant
    non viene toccato.

    P2-6: è l'unico punto in cui l'ambiente resta un canale legittimo. `login_omoda.py` e
    `prova_token.py` sono PROCESSI SEPARATI: non possono ricevere un oggetto Python, e
    passare le stesse informazioni in argv le renderebbe visibili a tutta la macchina.
    Perciò la configurazione del contesto viene serializzata qui, per quella sola chiamata."""
    env = dict(os.environ)
    # ⚠️ I pacchetti che Home Assistant installa a RUNTIME (qui: il client TLS di ripiego)
    # possono finire in `<config>/deps`, che HA aggiunge al `sys.path` del PROPRIO processo e
    # basta — non esporta `PYTHONPATH`. Un sottoprocesso lanciato con lo stesso interprete non
    # li vedrebbe, e l'utente leggerebbe «installa curl_cffi» con curl_cffi già installato.
    # Il percorso si ricava dal token, che vive nella cartella di configurazione. Si accoda a
    # un `PYTHONPATH` esistente invece di sostituirlo, per non spegnere configurazioni altrui.
    deps = os.path.join(os.path.dirname(os.path.abspath(ctx.token_path)), "deps")
    if os.path.isdir(deps):
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in (env.get("PYTHONPATH", ""), deps) if p])
    env.update({
        "OMODA_EMAIL": ctx.email,
        # login via SMS: se il telefono è valorizzato, i sottoprocessi usano il ramo mobile
        "OMODA_PHONE": getattr(ctx, "phone", "") or "",
        "OMODA_AREA": getattr(ctx, "area_code", "39") or "39",
        "OMODA_TOKEN_PATH": ctx.token_path,
        "OMODA_BFF": ctx.bff,
        "TSP_HOST": ctx.tsp_host,
        "CHANNEL_ID": ctx.channel_id,
        "OMODA_COUNTRY_ID": ctx.country_id,
        "OMODA_TENANT_CODE": ctx.tenant_code,
        "VIN": ctx.vin,
        "TUSERID": ctx.tuserid,
    })
    env.update({k: str(v) for k, v in extra.items() if v is not None})
    return env


def _is_phone(ctx) -> bool:
    """True se questo account fa login via SMS (telefono valorizzato)."""
    return bool(getattr(ctx, "phone", "") or "")


def _num_mascherato(numero) -> str:
    """Ultime 4 cifre, il resto oscurato — vedi `core/mask.py` per la regola unica.

    ⚠️ Va applicato ALLA SORGENTE, non solo in fondo: le stringhe passate a `emit` non
    restano nel config flow — finiscono in `session_detail`, che è insieme lo stato di
    `sensor.omoda9_stato_sessione` (quindi recorder e backup) e un campo esportato
    VERBATIM nel file «Scarica diagnostica», fuori da ogni deny-list. Mascherare qui
    chiude i tre canali in un colpo solo; aggiungere `phone` a `TO_REDACT` non basterebbe,
    perché lì il numero è testo libero dentro una frase."""
    return mask.numero(numero)


def _riga_utile(out: str, rc: int) -> str:
    """La riga dell'output del sottoprocesso che spiega davvero cos'è andato storto.

    Due passaggi, in quest'ordine:

    1. **La riga marcata `MOTIVO:`**, se c'è. È la causa dichiarata esplicitamente dal
       sottoprocesso (`login_omoda._motivo`). Serve perché «l'ultima riga significativa» è un
       criterio fragile: quando la causa veniva stampata per prima e seguita da due righe di
       spiegazione, all'utente arrivava la coda di una frase («…pip install curl_cffi)») e
       l'errore vero spariva — proprio nel caso in cui la diagnosi serviva di più. Il marcatore
       è stabile: non dipende dall'ordine delle stampe né dal testo dei messaggi.
    2. Altrimenti, l'ultima riga significativa. Non l'ultima e basta: `login_omoda._emit_result`
       e `prova_token` chiudono sempre con la sentinella `RESULT: OK/FAIL`, quindi prendendo
       `[-1]` all'utente arrivava invariabilmente «RESULT: FAIL»."""
    righe = [r.strip() for r in (out or "").strip().splitlines()
             if r.strip() and not r.strip().startswith("RESULT:")]
    motivi = [r[len(_MOTIVO):].strip() for r in righe if r.startswith(_MOTIVO)]
    if motivi:
        return motivi[-1]
    return righe[-1] if righe else f"rc={rc}"


def request_otp(ctx, emit=lambda m: None):
    """Invia il codice OTP all'utente (email o SMS). True se l'invio è andato a buon fine."""
    src_dir, timeout = ctx.src_dir, _timeout()
    phone = _is_phone(ctx)
    # ramo mobile (SMS) vs email — l'invio SMS supera il WAF con la scala di client TLS di
    # `core/tls_client.py` (nessuna dipendenza obbligatoria: vedi lì il perché)
    cmd = ["login_omoda.py", "invia-sms"] if phone else ["login_omoda.py", "invia"]
    # ⚠️ MASCHERATI ENTRAMBI i rami. Qui il telefono era mascherato e l'e-mail no, nella
    # stessa espressione: la frase risultante («Codice inviato alla mail …») diventa
    # `session_detail`, che finisce verbatim nel file «Scarica diagnostica» — quello che il
    # README invita ad allegare alle issue di una repo PUBBLICA — e nello stato di
    # `sensor.omoda9_stato_sessione`, quindi in PostgreSQL e in ogni backup. L'intestazione di
    # `diagnostics.py` prometteva già «email → oscurata»: era falsa a partire da questa riga.
    dove = (f"al numero {mask.numero_con_prefisso(ctx.phone, ctx.area_code)}" if phone
            else f"alla mail {mask.indirizzo_email(ctx.email)}")
    emit(f"invio codice OTP {('via SMS ' if phone else '')}…")
    try:
        # identità via env (P1-4), non in argv: login_omoda.py rilegge OMODA_EMAIL / OMODA_PHONE.
        r = subprocess.run([PYEXE, *cmd],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout,
                           env=_subenv(ctx))
    except subprocess.TimeoutExpired:
        emit("timeout invio OTP — riprova")
        _LOGGER.warning("Omoda9 login: timeout invio OTP (%s)", "SMS" if phone else "email")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    # LOG per il debug/supporto: l'output del sottoprocesso (stato HTTP, chiave server, captcha).
    # ⚠️ DEBUG, non INFO: a INFO finirebbe in home-assistant.log di serie, e quel file l'utente
    # lo allega alle issue pubbliche. Il numero è già mascherato alla sorgente (login_omoda._mask)
    # ma il livello resta debug per prudenza: chi deve diagnosticare alza il livello e basta.
    _LOGGER.debug("Omoda9 login: invio OTP (%s) rc=%s\n%s",
                  "SMS" if phone else "email", r.returncode, out.strip())
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        emit(f"{'📱' if phone else '📧'} Codice inviato {dove} — inseriscilo nel campo «Codice OTP» e premi «Conferma»")
        return True
    emit(f"invio OTP fallito: {_riga_utile(out, r.returncode)[:120]}")
    return False


def confirm_otp(ctx, code, emit=lambda m: None):
    """Conia il token col codice OTP. Ritorna (ok, dettaglio)."""
    code = (code or "").strip()
    if not code:
        return False, "nessun codice inserito"
    src_dir, timeout = ctx.src_dir, _timeout()
    emit("conio il token col codice…")
    try:
        # email E codice OTP via env (P1-4), non in argv: il codice è una credenziale usa-e-getta
        # ma resterebbe comunque visibile in `ps` per tutta la durata della chiamata.
        r = subprocess.run([PYEXE, "prova_token.py"],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout,
                           env=_subenv(ctx, OMODA_OTP=code))
    except subprocess.TimeoutExpired:
        return False, "timeout conio token"
    out = (r.stdout or "") + (r.stderr or "")
    # LOG per il debug/supporto: prova_token stampa la FORMA del tentativo (identità mascherata,
    # lunghezza del codice, stato HTTP, chiave server). Token redatti da prova_token._redact,
    # OTP e numero mai in chiaro. ⚠️ DEBUG e non INFO: vedi la nota in request_otp.
    _LOGGER.debug("Omoda9 login: conio token (%s) rc=%s\n%s",
                  "SMS" if _is_phone(ctx) else "email", r.returncode, out.strip())
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        ok, _detail, _status = check(ctx)
        return ok, ("Sessione ripristinata ✅" if ok else "token coniato ma login ancora KO")
    return False, f"codice rifiutato: {_riga_utile(out, r.returncode)[:120]}"


if __name__ == "__main__":
    from .context import ctx_da_environ
    print("check:", check(ctx_da_environ()))
