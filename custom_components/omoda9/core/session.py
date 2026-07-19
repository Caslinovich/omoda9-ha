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
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# P2-2: import relativo di pacchetto (prima: nome nudo + `sys.path.insert(HERE)`).
from . import wake  # riusa _bff_login / _refresh_token / TOKEN_PATH

# P2-6: email e cartella sorgenti arrivano dal `CoreCtx` del veicolo, non più da global
# di modulo popolati da os.environ.
PYEXE     = sys.executable  # il python di Home Assistant (ha le requirements del manifest)
_TIMEOUT  = int(os.environ.get("OMODA_OTP_TIMEOUT", "120"))


# P1-1 (H7): marcatori STABILI dell'esito di check(). Il chiamante instrada il rimedio su
# questi, MAI sul testo umano (che è localizzato e può cambiare a ogni ritocco di copy).
STATUS_OK = "OK"                # login BFF riuscito col token attuale
STATUS_EXPIRED = "EXPIRED"      # token/sessione morti → serve un OTP nuovo (reauth)
STATUS_NET_ERROR = "NET_ERROR"  # errore di rete/transitorio → NON è una sessione scaduta


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
    return (False,
            "Sessione scaduta ❌ — premi «Richiedi codice OTP» (app ufficiale chiusa)",
            STATUS_EXPIRED)


def refresh(ctx):
    """Rinnova l'access_token col refresh_token (senza OTP). True se rinnovato."""
    try:
        return bool(wake._refresh_token(ctx))
    except Exception:
        return False


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
    env.update({
        "OMODA_EMAIL": ctx.email,
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


def request_otp(ctx, emit=lambda m: None):
    """Invia il codice OTP alla mail dell'utente. True se l'invio è andato a buon fine."""
    email, src_dir, timeout = ctx.email, ctx.src_dir, _timeout()
    emit("invio codice OTP alla mail…")
    try:
        # email via env (P1-4), non in argv: login_omoda.py la rilegge da OMODA_EMAIL.
        r = subprocess.run([PYEXE, "login_omoda.py", "invia"],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout,
                           env=_subenv(ctx))
    except subprocess.TimeoutExpired:
        emit("timeout invio OTP — riprova")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        emit(f"📧 Codice inviato a {email} — inseriscilo nel campo «Codice OTP» e premi «Conferma»")
        return True
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    emit(f"invio OTP fallito: {tail[:120]}")
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
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        ok, _detail, _status = check(ctx)
        return ok, ("Sessione ripristinata ✅" if ok else "token coniato ma login ancora KO")
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    return False, f"codice rifiutato: {tail[:120]}"


if __name__ == "__main__":
    from .context import ctx_da_environ
    print("check:", check(ctx_da_environ()))
