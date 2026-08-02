"""`core/mask.py` — la regola unica di mascheratura dei dati personali.

Perché questo file esiste. Prima dell'accodamento del login via SMS la stessa mascheratura
era scritta **quattro volte** (`core/session.py`, `core/login_omoda.py`, `core/prova_token.py`,
`coordinator.py`) e le quattro copie **stavano già dando risposte diverse** sullo stesso
ingresso: tre restituivano `***`, una il solo prefisso senza asterischi, e `_mask_identity`,
sotto le 4 cifre, restituiva **il valore in chiaro**. Il progetto aveva già scritto altrove la
morale («due copie della stessa regola divergono, e a divergere è sempre quella che ci si
dimentica di aggiornare»): qui la si presidia.

⚠️ Tutti i valori sono sintetici e portano il marcatore richiesto da `check_secrets.sh` sulla
RIGA del valore.
"""
from __future__ import annotations

import re

import pytest

from custom_components.omoda9.core import mask


# ───────────────────────────── numeri ─────────────────────────────

def test_lascia_vedere_solo_la_coda():
    assert mask.numero("3001234567") == "***4567"          # PHONE_PLACEHOLDER

def test_ignora_i_separatori():
    assert mask.numero("+39 300 123.45-67") == "***4567"   # PHONE_PLACEHOLDER


@pytest.mark.parametrize("valore", [
    "1234",           # PHONE_PLACEHOLDER: esattamente la lunghezza della coda
    "123",            # PHONE_PLACEHOLDER
    "12345",          # PHONE_PLACEHOLDER: una sola cifra resterebbe nascosta
    "", None, "abc", 0,
])
def test_non_restituisce_mai_il_valore_in_chiaro(valore):
    """Il difetto che questo file presidia: una mascheratura che si arrende sui casi limite.

    Con un valore di 4 cifre la vecchia formula produceva `***1234`, cioè il numero **intero**
    preceduto da asterischi; `_mask_identity` andava oltre e restituiva la stringa originale.
    Qui si pretende che la coda non basti mai da sola a ricostruire il valore."""
    uscita = mask.numero(valore)
    cifre = mask.solo_cifre(valore)
    assert uscita == mask.OSCURATO or len(cifre) - len(uscita.replace(mask.OSCURATO, "")) >= 2
    assert cifre not in uscita or not cifre


def test_prefisso_sempre_con_asterischi():
    """`coordinator._num_avviso` col numero corto restituiva il solo `+39`, cioè una frase
    che sembrava completa e non segnalava affatto di essere stata mascherata."""
    assert mask.numero_con_prefisso("12", "39") == "+39 ***"          # PHONE_PLACEHOLDER
    assert mask.numero_con_prefisso("3001234567", "39") == "+39 ***4567"  # PHONE_PLACEHOLDER


# ───────────────────────────── e-mail ─────────────────────────────

def test_email_perde_la_parte_che_identifica_la_persona():
    assert mask.indirizzo_email("mario.rossi@example.com") == "m***@example.com"

@pytest.mark.parametrize("valore", ["", None, "senza-chiocciola", "@", "tizio@"])
def test_email_malformata_non_esce_mai(valore):
    assert "@" not in mask.indirizzo_email(valore).replace("***@", "") or \
        mask.indirizzo_email(valore) == mask.OSCURATO
    assert str(valore or "") not in (mask.indirizzo_email(valore),) or not valore


# ───────────────────────── identità composita ─────────────────────────

def test_identita_tiene_la_forma_e_butta_il_numero():
    """La forma `APP-LOGIN@<num>_<area>` è ciò che si sta verificando quando si legge un log
    di login: va conservata, il numero no."""
    assert mask.identita_mobile("APP-LOGIN@3001234567_39") == "APP-LOGIN@***4567_39"  # PHONE_PLACEHOLDER

def test_identita_di_forma_inattesa_non_tira_a_indovinare():
    assert mask.identita_mobile("3001234567") == "***4567"            # PHONE_PLACEHOLDER
    assert mask.identita_mobile("APP-LOGIN@12_39") == "APP-LOGIN@***_39"  # PHONE_PLACEHOLDER
    assert mask.identita_mobile("") == mask.OSCURATO


# ──────────────────── le due copie del pattern e-mail ────────────────────

@pytest.mark.parametrize("ingresso,vietato", [
    ("mario@rossi.it_39", "mario"),      # la «testa» non è il modulo: non va ristampata
    ("A@B@C_39", "B"),                   # chiocciole multiple
    ("mario.rossi@example.com", "mario"),
])
def test_identita_non_ristampa_una_testa_che_non_e_il_modulo(ingresso, vietato):
    """`rpartition('@')` da sola non verifica NULLA: prendeva per «modulo» qualunque cosa
    precedesse l'ultima chiocciola e la ristampava in chiaro. Con un valore che arriva grezzo
    dall'ambiente (`OMODA_PHONE` non passa dalla normalizzazione del config flow) usciva un
    indirizzo intero."""
    assert vietato not in mask.identita_mobile(ingresso)


def test_email_con_chiocciole_multiple_taglia_sull_ultima():
    """`partition` sulla PRIMA chiocciola trattava `@b.com` come parte del nome e restituiva
    `a***@@b.com`. Il dominio vero è quello dopo l'ULTIMA chiocciola; la parte da nascondere è
    tutto ciò che sta prima."""
    assert mask.indirizzo_email("a@@b.com") == "a***@b.com"
    assert mask.indirizzo_email("mario@rossi@example.com") == "m***@example.com"


@pytest.mark.parametrize("ingresso", [["a@b.com"], {"a": "b@c.it"}, 42, object()])
def test_email_su_valori_non_testuali_non_inventa(ingresso):
    """Su un valore che non è una stringa la vecchia versione mascherava la rappresentazione
    Python (la parentesi quadra) lasciando intatto ciò che c'era dentro."""
    assert mask.indirizzo_email(ingresso) == mask.OSCURATO


@pytest.mark.parametrize("prefisso", ["+39", "0039", "", None, "abc"])
def test_prefisso_ripulito_nei_testi_utente(prefisso):
    """La frase che l'utente legge non deve mai contenere `++39` o `+None`: il prefisso arriva
    da un campo libero e da variabili d'ambiente."""
    uscita = mask.numero_con_prefisso("3001234567", prefisso)   # PHONE_PLACEHOLDER
    assert "++" not in uscita and "None" not in uscita and uscita.endswith("***4567")


def test_il_pattern_email_non_diverge_da_diag():
    """`diag.py` non può importare `core.mask` — viene caricato anche fuori dal pacchetto, con
    importlib, dal proprio test — e ne tiene una copia letterale. Questo test è ciò che
    sostituisce l'import: se qualcuno migliora una delle due, l'altra deve seguirla."""
    sorgente = (mask.__file__.rsplit("/core/", 1)[0] + "/diag.py")
    with open(sorgente, encoding="utf-8") as fh:
        testo = fh.read()
    assert mask.RE_EMAIL.pattern in testo, (
        "il pattern e-mail di core/mask.py non compare più in diag.py: le due copie sono "
        "divergute, allineale (o riscrivi questo test se la struttura è cambiata)")


def test_il_pattern_email_riconosce_gli_indirizzi_reali():
    for indirizzo in ("mario.rossi@example.com", "m+tag@sotto.dominio.co.uk", "a_b%c@x.it"):
        assert mask.RE_EMAIL.search(indirizzo), indirizzo
    assert not mask.RE_EMAIL.search("niente-chiocciola.example.com")


def test_la_maschera_non_e_rimascherabile_da_re_email():
    """`RE_EMAIL` non riconosce la forma già mascherata (prima della chiocciola c'è un
    asterisco). È un fatto, non una virtù: è proprio il motivo per cui serve un secondo
    pattern, altrimenti il dominio sopravviveva nel file di supporto."""
    assert not mask.RE_EMAIL.search(mask.indirizzo_email("mario.rossi@example.com"))


@pytest.mark.parametrize("frase", [
    "Codice inviato alla mail m***@example.com — inseriscilo",
    "Codice inviato alla mail mario.rossi@example.com — inseriscilo",
    "utente ***@sotto.dominio.co.uk non trovato",
])
def test_la_diagnostica_toglie_anche_il_dominio(frase):
    """Regressione: mascherare l'e-mail alla sorgente e fermarsi lì era un PEGGIORAMENTO per il
    canale pubblico. Prima l'indirizzo grezzo veniva sostituito per intero nel file «Scarica
    diagnostica»; con la sola mascheratura alla sorgente il dominio ricompariva, perché la rete
    di sicurezza non riconosceva più ciò che le arrivava davanti."""
    from custom_components.omoda9.diagnostics import _scrub_email

    uscita = _scrub_email({"session_detail": frase})["session_detail"]
    assert "example.com" not in uscita and "dominio.co.uk" not in uscita
    assert "**EMAIL**" in uscita
