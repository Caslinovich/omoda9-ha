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
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wake  # riusa _bff_login / _refresh_token / TOKEN_PATH

EMAIL     = os.environ.get("OMODA_EMAIL", "")   # PER-ACCOUNT: vedi omoda9.env.example
# Cartella con login_omoda.py / prova_token.py / omoda.py: di default sono in questa stessa
# cartella (pacchetto). Override con OMODA_SRC_DIR se vivono altrove.
OMODA_DIR = os.environ.get("OMODA_SRC_DIR", HERE)
PYEXE     = sys.executable  # il venv del ponte (ha captcha/sm4/requests)
_TIMEOUT  = int(os.environ.get("OMODA_OTP_TIMEOUT", "120"))


def check():
    """Ritorna (ok: bool, dettaglio: str). ok=True se un login BFF col token attuale riesce."""
    try:
        ut, tu = wake._bff_login()
    except Exception as e:
        return False, f"errore rete: {type(e).__name__}"
    if ut:
        return True, "Sessione attiva ✅"
    return False, "Sessione scaduta ❌ — premi «Richiedi codice OTP» (app ufficiale chiusa)"


def refresh():
    """Rinnova l'access_token col refresh_token (senza OTP). True se rinnovato."""
    try:
        return bool(wake._refresh_token())
    except Exception:
        return False


def _call_env():
    """Legge gli input dell'ATTUALE tentativo da os.environ al momento della CHIAMATA, non
    all'import (stesso schema di wake._token_path). Il config flow scrive OMODA_EMAIL/OMODA_SRC_DIR
    in os.environ prima di ogni tentativo, ma questo modulo resta in cache in sys.modules: le
    costanti EMAIL/OMODA_DIR resterebbero congelate su ciò che ha visto il PRIMO tentativo → una
    mail sbagliata (o il passaggio a un altro account) continuava a fallire fino al riavvio di HA."""
    email = os.environ.get("OMODA_EMAIL", EMAIL)
    src_dir = os.environ.get("OMODA_SRC_DIR", OMODA_DIR)
    try:
        timeout = int(os.environ.get("OMODA_OTP_TIMEOUT", str(_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _TIMEOUT
    return email, src_dir, timeout


def request_otp(emit=lambda m: None):
    """Invia il codice OTP alla mail dell'utente. True se l'invio è andato a buon fine."""
    email, src_dir, timeout = _call_env()
    emit("invio codice OTP alla mail…")
    try:
        r = subprocess.run([PYEXE, "login_omoda.py", "invia", email],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout)
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


def confirm_otp(code, emit=lambda m: None):
    """Conia il token col codice OTP. Ritorna (ok, dettaglio)."""
    code = (code or "").strip()
    if not code:
        return False, "nessun codice inserito"
    email, src_dir, timeout = _call_env()
    emit("conio il token col codice…")
    try:
        r = subprocess.run([PYEXE, "prova_token.py", email, code],
                           cwd=src_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout conio token"
    out = (r.stdout or "") + (r.stderr or "")
    # H7: esito su returncode + sentinella stabile, non su sottostringhe localizzate
    if r.returncode == 0 and "RESULT: OK" in out:
        ok, detail = check()
        return ok, ("Sessione ripristinata ✅" if ok else "token coniato ma login ancora KO")
    tail = out.strip().splitlines()[-1] if out.strip() else f"rc={r.returncode}"
    return False, f"codice rifiutato: {tail[:120]}"


if __name__ == "__main__":
    print("check:", check())
