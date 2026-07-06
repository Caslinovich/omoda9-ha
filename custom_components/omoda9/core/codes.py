#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — Mappa UNICA dei codici di risposta tspconsole/BFF Chery → testo leggibile.

Sorgente di verità per i SOLI testi diagnostici mostrati all'utente (HA/monitor).
Prima della FASE 1 lo stesso codice (es. A07900) aveva 3 significati diversi
sparsi in commands/wake/probe/provision; questa mappa li unifica. NON cambia la
logica dei comandi: i moduli decidono il flusso sui codici, qui c'è solo la
traduzione del codice in una frase.

⚠️ Alcuni codici (in primis A07900) sono CONTESTUALI sul backend Chery: il testo
qui è quello più ricorrente/utile; ogni chiamante può aggiungere contesto.
"""

# Codice → frase leggibile (italiano, per non tecnici).
CODE_MEANING = {
    "000000": "ok ✅",
    "A00079": "comando accettato ✅",
    # A00082: l'auto è OCCUPATA (processa un comando alla volta) → il comando NON è stato
    # eseguito. Transitorio: riprovare tra qualche secondo (verificato live 2026-06-21).
    "A00082": "auto occupata ⏳ (un altro comando è in corso) — riprova tra qualche secondo",
    # A00084 (i18n: "No vehicle control command permission"): l'account/veicolo non ha il
    # permesso PER QUEL comando. Visto dal vivo su remoteStart (2026-06-21): la nostra Omoda 9
    # non consente l'avvio remoto del motore, mentre clima/serratura/GPS funzionano.
    "A00084": "comando non consentito su questa auto 🚫 (permesso negato per questa funzione)",
    "A00089": "taskId non valido ❌ (serve un taskId benedetto da checkPassword)",
    "A00546": "taskId non valido ❌ (scene errato in checkPassword)",
    "A00567": "parametri checkPassword incompleti ❌",
    "A00000": "token scaduto/non valido ❌ (rifai il login OTP)",
    "A07312": "rate-limit sveglia 🚫 (l'auto rifiuta altre sveglie ora, riprova più tardi)",
    # A07900 è contestuale: in poll/probe = auto a riposo; coi comandi = firma o
    # car_token non validi. Testo neutro che copre il caso più frequente.
    "A07900": "auto a riposo / non raggiungibile (o firma/car_token non validi) ⌛",
}


def meaning(code, default=None):
    """Ritorna la frase leggibile per `code`. Se sconosciuto ritorna `default`
    (o una stringa generica col codice grezzo). Accetta anche code=None/non-str."""
    if code is None:
        return default if default is not None else "nessun codice"
    key = str(code)
    if key in CODE_MEANING:
        return CODE_MEANING[key]
    return default if default is not None else f"codice {key}"


if __name__ == "__main__":
    for c in ("000000", "A00079", "A07900", "A99999", None):
        print(f"{c!s:>8} -> {meaning(c)}")
