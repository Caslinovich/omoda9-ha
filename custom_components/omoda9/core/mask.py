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

# La forma GIÀ mascherata (`m***@dominio.it`). Serve perché `RE_EMAIL` non la riconosce — un
# asterisco non è un carattere ammesso prima della chiocciola — e senza questo pattern il
# dominio, che nella frase a schermo è voluto, sopravviveva anche nel file di supporto
# pubblicato. I due canali vogliono cose diverse e vanno serviti separatamente.
RE_EMAIL_MASCHERATA = re.compile(r"[A-Za-z0-9._%+-]*\*+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

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
    """`+39 ***1234` — la forma usata nei testi rivolti all'utente.

    Il prefisso viene ridotto alle sole cifre: arriva da un campo di testo libero e da variabili
    d'ambiente, e senza questo passaggio uscivano frasi come `++39 ***1234` o `+None ***`, che
    fanno sembrare rotta l'integrazione proprio nel messaggio che dovrebbe rassicurare."""
    cifre = solo_cifre(prefisso).lstrip("0")
    return f"+{cifre} {numero(valore)}" if cifre else numero(valore)


def indirizzo_email(valore) -> str:
    """`mario.rossi@example.com` → `m***@example.com`.

    Si tiene la prima lettera e il dominio: l'utente riconosce il proprio indirizzo nel form,
    e chi legge un log non ha la parte che identifica la persona.

    ⚠️ IL DOMINIO RESTA — a schermo. Per un indirizzo aziendale racconta dove uno lavora, e
    sarebbe troppo per un file pubblicato; ma toglierlo dalla frase che l'utente legge mentre
    aspetta il codice gli toglierebbe l'unica conferma che il codice sta andando dove deve.
    I due canali vogliono cose diverse, e vengono serviti separatamente: qui la forma
    leggibile, e in fondo a `diagnostics.py` una passata che sostituisce **anche questa forma
    mascherata** con `**EMAIL**` (per quello esiste `RE_EMAIL_MASCHERATA`: `RE_EMAIL` da sola
    non la riconosce, perché prima della chiocciola c'è un asterisco). Nel file di supporto il
    dominio quindi non c'è; nel dialogo sì."""
    s = str(valore).strip() if isinstance(valore, str) else ""
    # `rpartition`, non `partition`: con `a@@b.com` la parte locale è `a@` e il dominio è
    # `b.com`. Tagliando sulla PRIMA chiocciola il dominio restava intero dentro ciò che si
    # credeva la parte locale, e usciva in chiaro.
    locale, chiocciola, dominio = s.rpartition("@")
    if not chiocciola or not dominio or not locale:
        return OSCURATO
    return f"{locale[0]}{OSCURATO}@{dominio}"


def identita_mobile(valore) -> str:
    """`APP-LOGIN@<numero>_<prefisso>` → `APP-LOGIN@***1234_39`.

    Tiene la FORMA dell'identità composita — che è poi ciò che si sta verificando quando si
    legge un log di login — e butta il numero. Se la stringa non ha la forma attesa non si
    tira a indovinare: si maschera tutto tranne la coda."""
    s = str(valore or "")
    testa, chiocciola, coda = s.rpartition("@")
    # ⚠️ La testa si ristampa SOLO se è il modulo che ci aspettiamo. `rpartition` da sola non
    # verifica nulla: con un ingresso come `mario@rossi.it_39` la «testa» sarebbe `mario` e
    # sarebbe uscita in chiaro. Qui non si sa che cosa sia quella stringa, quindi non la si
    # ripete: la regola di questo modulo è che nel dubbio non passa niente.
    # Il modulo che produciamo è `APP-LOGIN`: lettere MAIUSCOLE e trattini. Richiederlo in
    # quella forma, e non «una qualunque parola», è ciò che distingue un'identità nostra da una
    # stringa arbitraria — `mario@rossi.it_39` passava il controllo «è alfabetico» e usciva col
    # nome in chiaro. Se un domani il modulo cambiasse forma, la mascheratura diventerebbe più
    # aggressiva, mai più permissiva: è il verso giusto in cui sbagliare.
    modulo_noto = bool(chiocciola) and testa.isascii() and testa.isupper() \
        and testa.replace("-", "").isalpha()
    corpo = coda if chiocciola else s
    num, sep, area = corpo.rpartition("_")
    prefisso_testa = f"{testa}@" if modulo_noto else ""
    if not sep:                                   # forma inattesa: nessuna deduzione
        return f"{prefisso_testa}{numero(corpo)}"
    return f"{prefisso_testa}{numero(num)}{sep}{area}"
