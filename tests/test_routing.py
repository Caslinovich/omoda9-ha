"""Tabella unica di instradamento (P2-5).

`test_command_routing.py` verifica le classificazioni *attraverso* `commands`, cioè come
le vive l'utente. Qui si verifica la tabella in sé e — soprattutto — la proprietà che dà
senso al refactor: **tutti i percorsi passano di lì**.

Era proprio questo a mancare. Il fallback della sveglia aveva una catena di `if` propria,
scritta a mano e mai riallineata: classificava come «PIN errato» rifiuti che erano di
permessi o di sessione. L'utente vedeva il rimedio sbagliato e, nel frattempo, si
bruciava un tentativo verso il blocco dell'account reale.
"""
from __future__ import annotations

import pytest

import fixtures as FX
from custom_components.omoda9.core import routing as R


# ───────────────────────── la tabella ─────────────────────────
@pytest.mark.parametrize("code,atteso", sorted(FX.CHECKPASSWORD_CODES.items()))
def test_checkpassword_reason(code, atteso):
    esito = R.classifica(code, R.CONTESTO_CHECKPASSWORD)
    assert esito.reason == atteso["reason"], f"{code} ({atteso['note']})"


@pytest.mark.parametrize("code,atteso", sorted(FX.CHECKPASSWORD_CODES.items()))
def test_checkpassword_lockout(code, atteso):
    """Solo i codici davvero imputabili al PIN contano verso il blocco dell'account."""
    esito = R.classifica(code, R.CONTESTO_CHECKPASSWORD)
    assert esito.conta_lockout is atteso["counts_lockout"], f"{code} ({atteso['note']})"


@pytest.mark.parametrize("code,atteso", sorted(FX.COMMAND_CODES.items()))
def test_comando_esito(code, atteso):
    esito = R.classifica(code, R.CONTESTO_COMANDO)
    assert esito.successo is atteso["ok"], f"{code} ({atteso['note']})"
    assert esito.reason == atteso["reason"], f"{code} ({atteso['note']})"
    assert esito.retryable is atteso["retryable"], f"{code} ({atteso['note']})"


def test_lo_stesso_codice_puo_significare_cose_diverse():
    """`A00567` è il caso che giustifica il parametro `contesto`.

    In `checkPassword` è una richiesta incompleta — il PIN può essere giusto, quindi
    nessun Repair. In risposta a un comando è un taskId da rifare: si riconia e si
    riprova. Trattarli allo stesso modo significa o mandare l'utente a cambiare un PIN
    sano, o non riprovare quando basterebbe."""
    cp = R.classifica("A00567", R.CONTESTO_CHECKPASSWORD)
    cmd = R.classifica("A00567", R.CONTESTO_COMANDO)

    assert cp.reason == R.REASON_CONFIG
    assert cp.conta_lockout is False
    assert cmd.riconia_taskid is True


def test_default_asimmetrico_fra_i_contesti():
    """Un codice mai visto: conservativo in checkPassword (ramo PIN, così un rimedio
    l'utente ce l'ha), non bloccante per un comando (non si inventa un fallimento)."""
    ignoto = "A0ZZZZ"
    assert R.classifica(ignoto, R.CONTESTO_CHECKPASSWORD).reason == R.REASON_PIN
    assert R.classifica(ignoto, R.CONTESTO_CHECKPASSWORD).conta_lockout is True

    cmd = R.classifica(ignoto, R.CONTESTO_COMANDO)
    assert cmd.fallimento is False
    assert cmd.successo is False


def test_codice_assente_non_esplode():
    """Risposta illeggibile o senza `code`: deve classificare, non sollevare."""
    for valore in (None, "", 0):
        assert R.classifica(valore, R.CONTESTO_COMANDO) is not None
        assert R.classifica(valore, R.CONTESTO_CHECKPASSWORD) is not None


# ───────────────────────── reason → azione ─────────────────────────
@pytest.mark.parametrize("reason,azione", [
    (R.REASON_REAUTH, R.AZIONE_REAUTH),
    (R.REASON_PIN, R.AZIONE_REPAIR_PIN),
    (R.REASON_CONFIG, R.AZIONE_AVVISO),
    (R.REASON_NESSUNO, R.AZIONE_AVVISO),
])
def test_azione_per_reason(reason, azione):
    assert R.azione_per_reason(reason) == azione


def test_reason_sconosciuto_degrada_ad_avviso():
    """Mai un'azione invasiva per un `reason` che non si conosce: far rifare un OTP o
    aprire un Repair che l'utente non può risolvere è peggio che non fare nulla."""
    assert R.azione_per_reason("qualcosa_di_nuovo") == R.AZIONE_AVVISO


# ───────────────────────── gli insiemi derivati ─────────────────────────
def test_gli_insiemi_derivano_dalla_tabella():
    """Erano elenchi scritti a mano accanto alla tabella: potevano divergere in silenzio
    da come i codici venivano davvero instradati."""
    from custom_components.omoda9.core import commands

    assert commands.SUCCESS_CODES is R.SUCCESS_CODES
    assert commands.FAILURE_CODES is R.FAILURE_CODES
    assert commands.RETRYABLE_CODES is R.RETRYABLE_CODES
    assert commands.TASKID_INVALID is R.TASKID_INVALID
    assert not (R.SUCCESS_CODES & R.FAILURE_CODES), "un codice non può essere ok E ko"


def test_ogni_codice_instradato_ha_un_testo_leggibile():
    """Le decisioni stanno in `routing`, i testi in `codes`: separati per la regola H7.
    Ma un codice che il componente instrada e non sa spiegare arriva all'utente muto."""
    from custom_components.omoda9.core import codes

    senza_testo = sorted(
        c for c in (R.SUCCESS_CODES | R.FAILURE_CODES) if c not in codes.CODE_MEANING
    )
    assert not senza_testo, f"codici instradati ma senza frase in codes.py: {senza_testo}"


# ───────────────────────── un solo instradamento, due percorsi ─────────────────────────
@pytest.mark.parametrize("reason,attesa", [
    ("reauth", "reauth"),
    ("pin", "repair_pin"),
    ("config", "avviso"),
    (None, "avviso"),
])
async def test_comando_ui_e_fallback_sveglia_instradano_uguale(
        hass, integrazione_avviata, monkeypatch, reason, attesa):
    """La proprietà che dà senso a P2-5: il comando dalla UI e il fallback della sveglia
    devono produrre la STESSA azione a parità di causa.

    Prima erano due catene di `if` indipendenti e il fallback classificava male: un PIN
    errato lì bruciava un tentativo in silenzio, senza Repair né riautenticazione."""
    from custom_components.omoda9.const import DOMAIN
    from custom_components.omoda9.core.commands import CommandError

    coord = hass.data[DOMAIN][integrazione_avviata.entry_id]
    errore = CommandError("rifiutato", code="A00000", reason=reason)

    azioni: list[str] = []
    monkeypatch.setattr(coord, "_raise_pin_issue", lambda d: azioni.append("repair_pin"))
    monkeypatch.setattr(coord.entry, "async_start_reauth", lambda h: azioni.append("reauth"))

    # percorso 1: comando dalla UI (sul loop)
    assert coord._instrada_rimedio(errore, dal_loop=True) == attesa
    # percorso 2: fallback della sveglia (da executor)
    assert coord._instrada_rimedio(errore, dal_loop=False) == attesa
    await hass.async_block_till_done()

    if attesa == "avviso":
        assert azioni == [], "un avviso non deve innescare rimedi automatici"
    else:
        assert len(azioni) == 2, f"i due percorsi non hanno agito allo stesso modo: {azioni}"
        assert set(azioni) == {attesa}
