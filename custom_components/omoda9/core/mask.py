#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mask.py — mascheratura UNICA dei dati personali nei testi che escono dal componente.

Perché sta qui e non ripetuta nei file che la usano. Il progetto ha già scritto la regola a
proposito di un altro caso (`diagnostics.py`, a proposito di `scrub_coordinates`): *«due copie
della stessa regola divergono, e a divergere è sempre quella che ci si dimentica di
aggiornare»*. Con l'arrivo del login via SMS le copie erano diventate **quattro** —
`core/session.py`, `core/login_omoda.py`, `core/prova_token.py`, `coordinator.py` — e stavano
già dando risposte diverse sullo stesso ingresso: tre restituivano `***`, una restituiva
`+39` senza asterischi, e una quarta, sotto le 4 cifre, restituiva **il valore in chiaro**.

DOVE FINISCONO QUESTE STRINGHE (il motivo per cui la mascheratura va fatta ALLA SORGENTE e
non in fondo): le frasi costruite con questi helper non restano nel form del config flow.
Diventano `session_detail`, che è insieme lo stato di `sensor.omoda9_stato_sessione` — quindi
recorder, PostgreSQL e ogni backup — e un campo esportato **verbatim** nel file «Scarica
diagnostica», che il README invita ad allegare alle issue di una repo **pubblica**. Mascherare
alla sorgente chiude tutti i canali in un colpo solo; una deny-list per chiave non basterebbe,
perché qui il dato sta dentro una frase in linguaggio naturale.

REGOLA: **mai il valore in chiaro, nemmeno come ripiego.** Una funzione di mascheratura che in
qualche ramo restituisce l'originale non è una mascheratura: è una mascheratura che fallisce
in silenzio proprio sui casi che nessuno ha provato.
"""
from __future__ import annotations

import re

# Indirizzo e-mail in un testo qualsiasi. Serve in due posti che non si parlavano: la
# redazione del monitor diagnostico (`diag.py`) e la passata finale del file «Scarica
# diagnostica» (`diagnostics.py`). Averne due copie significava, come sempre, che una delle
# due mancava — ed era quella del file che l'utente allega alle issue pubbliche.
# ⚠️ `diag.py` NON può importare da qui (viene caricato anche fuori dal pacchetto, con
# importlib, dal suo test) e ne tiene perciò una copia letterale: a impedire che le due
# divergano c'è `tests/test_mask.py::test_il_pattern_email_non_diverge_da_diag`.
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Quante cifre finali si lasciano vedere. Bastano a far dire all'utente «sì, è il mio numero»
# senza che chi legge il log possa richiamarlo.
CODA = 4
# Quante cifre devono restare comunque nascoste perché la coda non equivalga al numero intero.
# Senza questo, un valore di 4 cifre usciva come `***1234`, cioè per intero con tre asterischi
# davanti. I numeri veri hanno almeno 6 cifre (lo impone `_normalizza_telefono`), quindi la
# soglia non toglie nulla all'uso normale e copre i casi limite e i dati malformati.
MIN_NASCOSTE = 2

OSCURATO = "***"


def solo_cifre(valore) -> str:
    return "".join(ch for ch in str(valore or "") if ch.isdigit())


def numero(valore) -> str:
    """Numero di telefono → `***1234`, oppure `***` se è troppo corto perché la coda basti
    da sola a ricostruirlo."""
    cifre = solo_cifre(valore)
    return f"{OSCURATO}{cifre[-CODA:]}" if len(cifre) >= CODA + MIN_NASCOSTE else OSCURATO


def numero_con_prefisso(valore, prefisso) -> str:
    """`+39 ***1234` — la forma usata nei testi rivolti all'utente."""
    return f"+{prefisso} {numero(valore)}"


def indirizzo_email(valore) -> str:
    """`mario.rossi@example.com` → `m***@example.com`.

    Si tiene la prima lettera e il dominio: l'utente riconosce il proprio indirizzo nel form,
    e chi legge un log non ha la parte che identifica la persona. ⚠️ Il dominio resta visibile,
    e per un indirizzo aziendale racconta comunque dove uno lavora: per questo `diagnostics.py`
    applica in fondo anche una passata che sostituisce **qualunque** indirizzo con `**EMAIL**`,
    così ciò che esce nel file di supporto non ne conserva traccia. Qui si sceglie il compromesso
    leggibile perché la stessa frase è anche quella che l'utente legge a schermo."""
    s = str(valore or "").strip()
    locale, chiocciola, dominio = s.partition("@")
    if not chiocciola or not dominio:
        return OSCURATO
    return f"{locale[0]}{OSCURATO}@{dominio}" if locale else f"{OSCURATO}@{dominio}"


def identita_mobile(valore) -> str:
    """`APP-LOGIN@<numero>_<prefisso>` → `APP-LOGIN@***1234_39`.

    Tiene la FORMA dell'identità composita — che è poi ciò che si sta verificando quando si
    legge un log di login — e butta il numero. Se la stringa non ha la forma attesa non si
    tira a indovinare: si maschera tutto tranne la coda."""
    s = str(valore or "")
    testa, chiocciola, coda = s.rpartition("@")
    corpo = coda if chiocciola else s
    num, sep, area = corpo.rpartition("_")
    prefisso_testa = f"{testa}@" if chiocciola else ""
    if not sep:                                   # forma inattesa: nessuna deduzione
        return f"{prefisso_testa}{numero(corpo)}"
    return f"{prefisso_testa}{numero(num)}{sep}{area}"
