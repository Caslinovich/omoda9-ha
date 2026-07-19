#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tabella UNICA di instradamento dei codici backend (P2-5 / D1).

**Cosa decide questo modulo.** Il backend Chery risponde sempre HTTP 200 e mette
l'esito vero in un `code` (`A00xxx`). Da quel codice discendono quattro decisioni
indipendenti, che prima vivevano sparse fra `commands.send`, `commands._checkpassword`
e due punti del coordinator:

1. il comando è andato a buon fine?
2. quale **rimedio** proporre all'utente (`reason`) — e quindi quale azione compie Home
   Assistant: riautenticazione, Repair del PIN, o solo un avviso;
3. l'errore va **contato** verso l'anti-lockout del PIN?
4. conviene **riconiare il taskId** e riprovare?

Tenerle sparse aveva un costo misurabile: il fallback della sveglia classificava come
«PIN errato» rifiuti che erano di permessi o di sessione, quindi mostrava il rimedio
sbagliato e — peggio — avvicinava il blocco dell'account reale per una causa che col PIN
non c'entrava nulla.

**Divisione dei compiti.** Qui stanno le DECISIONI; in `codes.py` restano i TESTI
leggibili. È la regola H7 del progetto: non si decide mai su una stringa localizzata,
perché tradurre o riformulare un messaggio non deve poter disattivare la riautenticazione.

**Il contesto conta.** Lo stesso codice può significare cose diverse a seconda di dove
arriva: `A00567` durante `checkPassword` è una richiesta malformata (non è il PIN), ma in
risposta a un comando significa «taskId non valido» → si riconia e si riprova. Per questo
`classifica()` chiede sempre il contesto.

**Il default è deliberatamente asimmetrico.** Un codice sconosciuto in `checkPassword`
finisce sul ramo PIN (conservativo: meglio proporre di ricontrollare il PIN che lasciare
l'utente senza rimedio), mentre in risposta a un comando resta non bloccante — non si
inventa un fallimento che il backend non ha dichiarato.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# ───────────────────────── rimedi (`reason`) ─────────────────────────
# Valori STABILI: il coordinator instrada su questi, mai sul testo del messaggio.
REASON_PIN = "pin"        # PIN comandi errato → Repair «PIN comandi errato»
REASON_REAUTH = "reauth"  # sessione/token morti → riautenticazione nativa HA (nuovo OTP)
REASON_CONFIG = "config"  # né PIN né sessione (permessi, richiesta malformata) → solo avviso
REASON_NESSUNO = None     # rifiuto dell'auto (occupata / non consentito / a riposo) → avviso

# ───────────────────────── azioni del coordinator ─────────────────────────
AZIONE_REAUTH = "reauth"          # entry.async_start_reauth
AZIONE_REPAIR_PIN = "repair_pin"  # apre l'avviso di riparazione del PIN
AZIONE_AVVISO = "avviso"          # nessun rimedio automatico: si mostra e basta

_AZIONE_PER_REASON = {
    REASON_REAUTH: AZIONE_REAUTH,
    REASON_PIN: AZIONE_REPAIR_PIN,
    REASON_CONFIG: AZIONE_AVVISO,
    REASON_NESSUNO: AZIONE_AVVISO,
}


def azione_per_reason(reason: str | None) -> str:
    """Rimedio → azione concreta di Home Assistant.

    Un `reason` sconosciuto degrada ad avviso: mai a un'azione invasiva come far
    rifare un OTP o aprire un Repair che l'utente non può risolvere."""
    return _AZIONE_PER_REASON.get(reason, AZIONE_AVVISO)


# ───────────────────────── contesti ─────────────────────────
CONTESTO_CHECKPASSWORD = "checkpassword"  # conio del taskId (verifica del PIN)
CONTESTO_COMANDO = "comando"              # invio di un comando all'auto


@dataclass(frozen=True)
class Classificazione:
    """Cosa fare di un codice, in un contesto."""

    code: str | None = None
    reason: str | None = REASON_NESSUNO
    # esito dell'invio: "ok" accettato, "ko" rifiutato, "ignoto" = il backend non si è
    # espresso in modo riconoscibile → non bloccante, per prudenza.
    esito: str = "ignoto"
    retryable: bool = False            # ha senso ritentare tale e quale (auto occupata)
    riconia_taskid: bool = False       # il taskId è da rifare: riconia e riprova UNA volta
    conta_lockout: bool = False        # incrementa l'anti-lockout del PIN

    @property
    def azione(self) -> str:
        return azione_per_reason(self.reason)

    @property
    def successo(self) -> bool:
        return self.esito == "ok"

    @property
    def fallimento(self) -> bool:
        return self.esito == "ko"


def _voce(**kw) -> Classificazione:
    return Classificazione(**kw)


# ───────────────────────── la tabella ─────────────────────────
# Valida in ENTRAMBI i contesti salvo override esplicito più sotto.
_TABELLA: dict[str, Classificazione] = {
    # — accettati —
    "000000": _voce(esito="ok"),
    "A00079": _voce(esito="ok"),

    # — rifiuti dell'auto: nessun rimedio automatico, solo avviso —
    # l'auto esegue UN comando alla volta → transitorio, ritentabile
    "A00082": _voce(esito="ko", retryable=True),
    # permesso negato per QUELLA funzione (visto dal vivo su remoteStart)
    "A00084": _voce(esito="ko"),
    "A07312": _voce(esito="ko"),   # rate-limit della sveglia
    "A07900": _voce(esito="ko"),   # auto a riposo / firma o car_token non validi

    # — taskId da rifare: si riconia e si riprova una volta —
    "A00089": _voce(esito="ko", riconia_taskid=True),
    "A00546": _voce(esito="ko", riconia_taskid=True),
    "A00567": _voce(esito="ko", riconia_taskid=True),

    # — sessione morta: l'unico rimedio è un OTP nuovo (il PIN è irrilevante) —
    "A00000": _voce(esito="ko", reason=REASON_REAUTH),

    # — non è il PIN: permessi sul veicolo o richiesta costruita male —
    # NON contano per l'anti-lockout: contarli avvicinerebbe il blocco dell'account
    # reale per una causa che col PIN non c'entra nulla (bug P1-2).
    "A00374": _voce(reason=REASON_CONFIG),   # permessi veicolo
    "A00554": _voce(reason=REASON_CONFIG),   # autorizzazione veicolo
    "A00604": _voce(reason=REASON_CONFIG),   # clientType mancante/errato
    "A00643": _voce(reason=REASON_CONFIG),   # taskId assente nella richiesta
    "A00757": _voce(reason=REASON_CONFIG),   # richiesta malformata
}

# Override per contesto. `A00567` è il caso da tenere a mente: in `checkPassword` è una
# richiesta incompleta (il PIN può essere giusto), in risposta a un comando è un taskId
# da rifare. Stesso codice, due rimedi diversi.
_OVERRIDE_CHECKPASSWORD: dict[str, Classificazione] = {
    "A00567": _voce(reason=REASON_CONFIG),
    # PIN/password errati: gli unici che devono davvero contare per il blocco.
    "A00285": _voce(reason=REASON_PIN, conta_lockout=True),
    "A00282": _voce(reason=REASON_PIN, conta_lockout=True),
}

# Codice mai visto. L'asimmetria è voluta — vedi il docstring del modulo.
_DEFAULT_CHECKPASSWORD = _voce(reason=REASON_PIN, conta_lockout=True)
_DEFAULT_COMANDO = _voce(esito="ignoto")


def classifica(code, contesto: str) -> Classificazione:
    """Codice backend → cosa fare, nel contesto dato.

    `code` può essere `None` o non-stringa (risposta illeggibile): viene normalizzato.
    """
    chiave = str(code) if code is not None else ""

    if contesto == CONTESTO_CHECKPASSWORD:
        voce = _OVERRIDE_CHECKPASSWORD.get(chiave) or _TABELLA.get(chiave)
        if voce is None:
            voce = _DEFAULT_CHECKPASSWORD
    else:
        voce = _TABELLA.get(chiave, _DEFAULT_COMANDO)

    return replace(voce, code=chiave or None)


# ───────────────────────── viste derivate (compatibilità) ─────────────────────────
# Insiemi ricavati DALLA tabella, non scritti a mano accanto: prima erano elenchi
# paralleli che potevano divergere in silenzio da come i codici venivano instradati.
SUCCESS_CODES = frozenset(c for c, v in _TABELLA.items() if v.esito == "ok")
FAILURE_CODES = frozenset(c for c, v in _TABELLA.items() if v.esito == "ko")
RETRYABLE_CODES = frozenset(c for c, v in _TABELLA.items() if v.retryable)
TASKID_INVALID = frozenset(c for c, v in _TABELLA.items() if v.riconia_taskid)


if __name__ == "__main__":
    for c in ("000000", "A00079", "A00082", "A00567", "A00285", "A00000", "A99999"):
        cp = classifica(c, CONTESTO_CHECKPASSWORD)
        cm = classifica(c, CONTESTO_COMANDO)
        print(f"{c:>8}  checkPassword: reason={cp.reason!s:<7} lockout={cp.conta_lockout!s:<5}"
              f" | comando: esito={cm.esito:<7} reason={cm.reason!s:<7} riconia={cm.riconia_taskid}")
