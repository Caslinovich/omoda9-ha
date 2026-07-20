"""`CoreCtx` (P2-6): la prova che lo stato condiviso di processo è davvero sparito.

Questi test non verificano un comportamento visibile all'utente: verificano una
**proprietà strutturale**. È deliberato — P2-6 esiste per rendere impossibili tre classi
di problemi che, con la configurazione su global di modulo, erano solo "improbabili":

* un comando che parte verso l'auto sbagliata quando ci sono due veicoli configurati;
* PIN ed email leggibili nell'ambiente del processo Home Assistant;
* l'ordine di esecuzione che cambia l'esito, perché lo stato sopravvive fra una
  chiamata e l'altra.
"""
from __future__ import annotations

import os

import pytest

import fixtures as FX
from custom_components.omoda9.core.context import CoreCtx


# ───────────────────────── indipendenza fra veicoli ─────────────────────────
def test_due_veicoli_hanno_stato_indipendente():
    """Il punto di P2-6: due auto configurate non devono interferire.

    Con lo stato in global di modulo, il blocco del PIN di un'auto avrebbe fermato i
    comandi dell'altra, e il taskId coniato per una sarebbe stato usato per l'altra."""
    a = CoreCtx(vin="VIN_A", pin="1111")
    b = CoreCtx(vin="VIN_B", pin="2222")

    with a.lockout.attempt() as tentativo:
        tentativo.fallito()
    a.stato.taskid = "taskid_di_a"

    assert a.lockout.tentativi_falliti == 1
    assert b.lockout.tentativi_falliti == 0, "il blocco di un'auto ha toccato l'altra"
    assert b.stato.taskid is None, "il taskId di un'auto è visibile all'altra"


def test_ogni_contesto_ha_i_propri_lock():
    """I lock erano di processo: due auto se li contendevano senza alcun motivo —
    svegliarne una bloccava la sveglia dell'altra."""
    a, b = CoreCtx(vin="A"), CoreCtx(vin="B")
    assert a.stato.lock_sveglia is not b.stato.lock_sveglia
    assert a.stato.lock_sonda is not b.stato.lock_sonda
    assert a.stato.lock_token is not b.stato.lock_token


def test_due_coordinator_due_contesti(hass, cloud, monkeypatch):
    """Verifica end-to-end della stessa proprietà, sui coordinator veri."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.omoda9.const import (
        CONF_EMAIL, CONF_PIN, CONF_TUSERID, CONF_VIN, DOMAIN,
    )
    from custom_components.omoda9.coordinator import Omoda9Coordinator

    def _coord(vin, pin):
        entry = MockConfigEntry(
            domain=DOMAIN, unique_id=vin,
            data={CONF_VIN: vin, CONF_TUSERID: FX.TUSERID,
                  CONF_EMAIL: FX.EMAIL, CONF_PIN: pin})
        entry.add_to_hass(hass)
        return Omoda9Coordinator(hass, entry)

    primo = _coord("LZZAAAAAA1B2C3D4E", "1111")     # VIN_PLACEHOLDER: sintetici
    secondo = _coord("LZZBBBBBB9Z8Y7X6W", "2222")

    assert primo.ctx is not secondo.ctx
    assert primo.ctx.vin != secondo.ctx.vin
    assert primo.ctx.pin != secondo.ctx.pin
    assert primo.ctx.token_path != secondo.ctx.token_path
    assert primo.ctx.taskid_file != secondo.ctx.taskid_file


# ───────────────────────── niente segreti nell'ambiente ─────────────────────────
async def test_ha_non_scrive_mai_segreti_nell_ambiente(hass, integrazione_avviata):
    """P1-4/P2-6, la garanzia forte.

    Prima il PIN e l'email finivano in `os.environ`, leggibile da qualunque cosa giri
    dentro Home Assistant (altre integrazioni, template, add-on con accesso a `/proc`);
    li si ripuliva all'unload. Ora non ci finiscono mai: non c'è nulla da ripulire, che
    è una garanzia diversa e migliore — non dipende dal fatto che l'unload avvenga."""
    for chiave in ("OMODA_PIN", "OMODA_EMAIL"):
        assert os.environ.get(chiave) is None, (
            f"{chiave} è finita nell'ambiente del processo Home Assistant"
        )
    # e nemmeno il valore, sotto qualunque nome
    for nome, valore in os.environ.items():
        assert valore != FX.PIN, f"il PIN compare in os.environ[{nome!r}]"


def test_l_ambiente_del_sottoprocesso_e_effimero(core, ctx):
    """L'unico uso legittimo dell'ambiente: i sottoprocessi di login sono processi
    SEPARATI e non possono ricevere un oggetto Python. La copia però dev'essere locale
    alla chiamata — non deve sporcare l'ambiente di Home Assistant."""
    session = core["session"]
    prima = dict(os.environ)

    env = session._subenv(ctx, OMODA_OTP="123456")

    assert env["OMODA_EMAIL"] == ctx.email
    assert env["OMODA_OTP"] == "123456"
    assert env["OMODA_TOKEN_PATH"] == ctx.token_path
    assert dict(os.environ) == prima, "os.environ è stato modificato dalla chiamata"


# ───────────────────────── niente configurazione nei global di modulo ─────────────────────────
@pytest.mark.parametrize("modulo,attributi", [
    ("commands", ("VIN", "PIN", "TSP_HOST", "TASKID_FILE", "MINT_TASKID",
                  "DIAG_HOOK", "_LOCKOUT", "_TASKID_CACHE", "_PIN_FAIL")),
    ("wake", ("VIN", "TSP_HOST", "TOKEN_PATH", "_TOKEN_LOCK", "_BUSY", "WAKE_STATE")),
    ("probe", ("VIN", "_BUSY", "_last_run")),
    ("session", ("EMAIL", "OMODA_DIR")),
])
def test_nessuna_configurazione_per_account_nei_global(core, modulo, attributi):
    """Guard-rail strutturale: reintrodurre un global per-account riaprirebbe in un colpo
    solo la classe di bug che P2-6 ha chiuso.

    NB: non è pedanteria — `commands.VIN` era *esattamente* il motivo per cui, con due
    entry, un comando poteva partire verso l'auto sbagliata."""
    mod = core[modulo]
    presenti = [a for a in attributi if hasattr(mod, a)]
    assert not presenti, (
        f"core/{modulo}.py ha ancora stato per-account a livello di modulo: {presenti}. "
        f"Deve vivere nel CoreCtx del veicolo."
    )


def test_il_contesto_porta_tutto_il_necessario():
    """Contratto del contesto: se un campo sparisce, i moduli core/ non hanno un
    ripiego globale su cui appoggiarsi — fallirebbero a runtime, non all'import."""
    ctx = CoreCtx()
    for campo in ("vin", "tuserid", "pin", "email", "token_path", "taskid_file",
                  "src_dir", "tsp_host", "bff", "channel_id", "country_id",
                  "tenant_code", "mint_taskid", "taskid_ttl", "diag_hook", "stato"):
        assert hasattr(ctx, campo), f"campo mancante nel CoreCtx: {campo}"


def test_percorsi_di_ripiego_solo_fuori_da_home_assistant():
    """Senza percorsi espliciti il contesto ne inventa di locali al pacchetto: va bene
    per la diagnostica da riga di comando, MAI in Home Assistant (dove sono per-VIN
    nella config dir). Il test fissa il comportamento perché è una scelta, non un caso."""
    ctx = CoreCtx()
    assert ctx.token_path.endswith("token.json")
    assert ctx.taskid_file.endswith("taskid.txt")


# ───────────────────────── il monitor non altera il flusso ─────────────────────────
def test_il_monitor_diagnostico_non_puo_rompere_un_comando():
    """Il monitor osserva, non partecipa: se il registratore esplode, il comando
    dell'utente deve proseguire comunque."""
    def hook_rotto(tipo, **campi):
        raise RuntimeError("registratore rotto")

    ctx = CoreCtx(diag_hook=hook_rotto)
    ctx.diag("pin_event", outcome="ok")   # non deve sollevare


def test_monitor_spento_e_dormiente():
    """A monitor spento il costo dev'essere nullo: nessuna allocazione, nessuna chiamata."""
    ctx = CoreCtx()
    assert ctx.diag_hook is None
    ctx.diag("qualcosa", campo=1)         # no-op
