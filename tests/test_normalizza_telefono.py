"""`_normalizza_telefono` — il punto unico in cui numero e prefisso vengono ripuliti.

Perché questo file esiste. Quella funzione è dichiarata dal codice stesso come l'unico
passaggio di pulizia: «da qui in poi viaggiano in entry.data, nell'ambiente dei sottoprocessi
e nell'identità `APP-LOGIN@<num>_<area>`, e a valle nessuno li tocca più». Non aveva un solo
test, e conteneva tre difetti che la suite non poteva vedere perché l'unico numero usato dai
fixture è proprio quello che la funzione trattava bene:

  * i cellulari italiani **391/392/393** — prefissi mobili realmente assegnati — venivano
    scambiati per il prefisso internazionale e **amputati**;
  * la forma `0039…` scritta nel campo numero non veniva riconosciuta (il confronto col
    prefisso paese avveniva prima della rimozione degli zeri) e usciva col prefisso duplicato;
  * un prefisso scritto ma illeggibile (`+`, `0`, `abc`) diventava **Italia** in silenzio, e il
    controllo che avrebbe dovuto impedirlo era codice morto.

⚠️ L'errore che questi test presidiano più di ogni altro è **l'amputazione**, non il tentativo
fallito: un numero mutilato viene ri-proposto nel form, l'utente lo rimanda identico, e se il
flow arriva in fondo finisce in `entry.data`, che `reconfigure` non permette di correggere.

⚠️ Tutti i numeri qui sono sintetici e portano il marcatore richiesto da `check_secrets.sh`
sulla RIGA del valore (l'allowlist del gate filtra per riga, non per blocco).
"""
from __future__ import annotations

import pytest

from custom_components.omoda9.config_flow import _normalizza_telefono
from custom_components.omoda9.const import DEFAULT_AREA_CODE


# (numero digitato, prefisso digitato, numero atteso, prefisso atteso, perché)
CASI = [
    # ── il caso normale ────────────────────────────────────────────────────────────────
    ("3001234567", "39", "3001234567", "39",                      # PHONE_PLACEHOLDER
     "numero nazionale scritto come chiede l'etichetta del campo: non si tocca"),
    ("300 123.45-67", "39", "3001234567", "39",                   # PHONE_PLACEHOLDER
     "separatori: spazi, punti, trattini"),

    # ── la regressione che rompeva il login per utenti reali ───────────────────────────
    ("3931234567", "39", "3931234567", "39",                      # PHONE_PLACEHOLDER
     "393 è un prefisso mobile italiano assegnato: NON è il prefisso internazionale"),
    ("3921234567", "39", "3921234567", "39",                      # PHONE_PLACEHOLDER
     "392 idem"),
    ("3911234567", "39", "3911234567", "39",                      # PHONE_PLACEHOLDER
     "391 idem"),

    # ── prefisso incollato davanti al numero ───────────────────────────────────────────
    ("393001234567", "39", "393001234567", "39",                  # PHONE_PLACEHOLDER
     "prefisso incollato SENZA +: non si sfila (non si distingue da un numero vero)"),
    ("+39 300 1234567", "39", "3001234567", "39",                 # PHONE_PLACEHOLDER
     "copiato dalla rubrica, con il + davanti"),
    ("0039 300 1234567", "39", "3001234567", "39",                # PHONE_PLACEHOLDER
     "forma internazionale lunga: era il caso non riconosciuto"),
    ("+39 393 1234567", "39", "3931234567", "39",                 # PHONE_PLACEHOLDER
     "il + è una dichiarazione esplicita: qui sfilare 39 è giusto anche su un numero 39x"),
    ("+44 (0)7912 345678", "44", "7912345678", "44",              # PHONE_PLACEHOLDER
     "prefisso E zero nazionale insieme: vanno tolti entrambi nella stessa passata"),
    ("7011234567", "7", "7011234567", "7",                        # PHONE_PLACEHOLDER
     "prefisso di UNA cifra: un nazionale da 10 non va scambiato per prefisso incollato"),
    ("4545123456", "45", "4545123456", "45",                      # PHONE_PLACEHOLDER
     "numerazione corta senza +: non si sfila, si preferisce il tentativo fallito"),

    # ── zero di accesso nazionale (fuori dall'Italia) ──────────────────────────────────
    ("07123456789", "44", "7123456789", "44",                     # PHONE_PLACEHOLDER
     "lo zero nazionale sparisce in E.164"),
    ("+49 176 12345678", "49", "17612345678", "49",               # PHONE_PLACEHOLDER
     "Germania in forma internazionale"),

    # ── prefisso ───────────────────────────────────────────────────────────────────────
    ("3001234567", "+39", "3001234567", "39",                     # PHONE_PLACEHOLDER
     "prefisso scritto col +"),
    ("3001234567", "0039", "3001234567", "39",                    # PHONE_PLACEHOLDER
     "prefisso scritto in forma lunga"),
    ("3001234567", "", "3001234567", DEFAULT_AREA_CODE,           # PHONE_PLACEHOLDER
     "casella vuota = vale il default"),
    ("3001234567", None, "3001234567", DEFAULT_AREA_CODE,         # PHONE_PLACEHOLDER
     "campo assente = vale il default"),

    # ── rifiuti ────────────────────────────────────────────────────────────────────────
    ("3001234567", "+", "", "",                                   # PHONE_PLACEHOLDER
     "prefisso SCRITTO ma illeggibile: non deve diventare Italia in silenzio"),
    ("3001234567", "0", "", "",                                   # PHONE_PLACEHOLDER
     "idem"),
    ("3001234567", "abc", "", "",                                 # PHONE_PLACEHOLDER
     "idem"),
    ("3001234567", "123456", "", "",                              # PHONE_PLACEHOLDER
     "un prefisso paese non ha sei cifre"),
    ("3001234567", "1234", "", "",                                # PHONE_PLACEHOLDER
     "nemmeno quattro: in E.164 il massimo è tre"),
    ("12345", "39", "", "", "troppo corto per essere un numero"),
    ("", "39", "", "", "vuoto"),
    (None, "39", "", "", "assente"),
    ("abcdef", "39", "", "", "nessuna cifra"),
    ("1234567890123456", "39", "", "", "oltre le 15 cifre di E.164"),
]


@pytest.mark.parametrize("numero,prefisso,atteso_num,atteso_pref,perche",
                         [pytest.param(*c, id=c[4][:48]) for c in CASI])
def test_normalizzazione(numero, prefisso, atteso_num, atteso_pref, perche):
    assert _normalizza_telefono(numero, prefisso) == (atteso_num, atteso_pref), perche


@pytest.mark.parametrize("numero,prefisso", [(c[0], c[1]) for c in CASI])
def test_e_idempotente(numero, prefisso):
    """Ripulire due volte deve dare lo stesso risultato di una.

    Non è un vezzo: dopo un invio fallito il form viene ri-proposto **coi valori già
    normalizzati**, quindi al secondo tentativo la funzione riceve la propria uscita. Se non
    fosse idempotente, ogni tentativo eroderebbe il numero un po' di più — che è esattamente
    come si comportava con i numeri 39x."""
    una = _normalizza_telefono(numero, prefisso)
    due = _normalizza_telefono(*una) if una[0] else una
    assert due == una


def test_e_idempotente_a_forza_bruta():
    """Idempotenza cercata dove NON l'ho scelta io.

    ⚠️ Il test qui sopra è una rete a maglie larghe: gira sui casi della lista, cioè su casi
    scelti da chi ha scritto la funzione. Una revisione indipendente ha trovato, con un fuzz su
    centinaia di migliaia di ingressi, che la versione precedente perdeva **una cifra a ogni
    ri-apertura del form** su prefissi da 1 cifra (Stati Uniti, Kazakistan) e su `+44 (0)…`,
    e questi test non se ne accorgevano. Da qui in poi la ricerca è esaustiva su un dominio
    ampio, non su una manciata di esempi comodi."""
    prefissi = ["1", "7", "39", "44", "45", "49", "41", "351", "352"]
    forme = ["{n}", "+{p} {n}", "00{p}{n}", "{p}{n}", "0{n}", "+{p} (0){n}"]
    scoperti = []
    for pref in prefissi:
        for coda in range(0, 1000, 7):                 # cifre finali variabili
            for lung in (6, 7, 8, 9, 10, 11):
                base = str(coda).rjust(lung, "8")      # PHONE_PLACEHOLDER: cifre sintetiche
                for forma in forme:
                    ingresso = forma.format(n=base, p=pref)
                    una = _normalizza_telefono(ingresso, pref)
                    if not una[0]:
                        continue
                    if _normalizza_telefono(*una) != una:
                        scoperti.append((ingresso, pref, una))
    assert not scoperti, (
        f"{len(scoperti)} ingressi non idempotenti — ognuno è una cifra persa a ogni "
        f"ri-apertura del form. Primi tre: {scoperti[:3]}")


def test_non_amputa_mai_un_numero_nazionale_plausibile():
    """Presidio della regola: nel dubbio non si taglia.

    Per ogni prefisso mobile italiano possibile (3xx) un numero di 10 cifre deve uscire
    intatto: nessuna combinazione di cifre iniziali può essere scambiata per il prefisso
    internazionale. È il controllo che la vecchia soglia di 6 cifre non superava."""
    for terza in range(10):
        numero = f"39{terza}1234567"            # PHONE_PLACEHOLDER: 391xxxxxxx … 399xxxxxxx
        assert _normalizza_telefono(numero, "39") == (numero, "39"), numero
    for seconda in range(10):
        numero = f"3{seconda}01234567"          # PHONE_PLACEHOLDER: 300xxxxxxx … 390xxxxxxx
        assert _normalizza_telefono(numero, "39") == (numero, "39"), numero
