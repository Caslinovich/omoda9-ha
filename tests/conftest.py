"""Fixture comuni della suite (P2-8).

Tre garanzie che valgono per TUTTI i test di questo pacchetto:

1. **Nessuna rete.** `no_network` è autouse: se un test dimentica di installare il
   trasporto finto, la chiamata esplode invece di partire davvero verso Chery. Su un
   progetto che comanda un'auto vera questa è una misura di sicurezza, non un dettaglio.
2. **Nessun segreto reale.** VIN/email/PIN/token sono sintetici (vedi `fixtures.py`),
   con lo stesso *formato* dei veri perché il codice li tratta per forma.
3. **Stato globale ripulito.** `core/` tiene lo stato in global di modulo (anti-lockout,
   cache taskId): senza reset fra un test e l'altro l'ordine di esecuzione cambierebbe
   l'esito. È esattamente il difetto strutturale che P2-3/P2-6 elimineranno — finché
   c'è, i test lo neutralizzano esplicitamente.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core_loader import load_core          # noqa: E402
from fake_cloud import FakeCloud           # noqa: E402
import fixtures as FX                      # noqa: E402

# Import ANTICIPATO del package: `custom_components` è un namespace package e Home
# Assistant, avviando l'istanza di test, ne rimappa il percorso sulla config dir
# temporanea. Importandolo qui — a tempo di collezione, prima che la fixture `hass`
# esista — resta fissato in sys.modules e i test lo trovano anche dentro le fixture.
# Senza questo, `from custom_components.omoda9...` funziona a livello di modulo ma
# fallisce con ModuleNotFoundError se eseguito a runtime.
from custom_components.omoda9 import const as OMODA_CONST   # noqa: E402

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """HA carica le integrazioni custom nei test solo se abilitate esplicitamente."""
    return enable_custom_integrations


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Rete vietata per default: un test che scorda il fake fallisce, non chiama Chery."""
    import socket

    def _blocked(*a, **kw):  # noqa: ANN002
        raise RuntimeError(
            "chiamata di rete REALE in un test: usa la fixture `cloud` (FakeCloud)"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture
def core():
    """I moduli `core/`.

    Dopo P2-6 non c'è più stato globale da azzerare fra un test e l'altro: la
    configurazione e lo stato per-veicolo vivono nel `CoreCtx` (fixture `ctx`), che nasce
    nuovo a ogni test. È esattamente il beneficio del refactor — prima l'ordine di
    esecuzione dei test poteva cambiarne l'esito."""
    return load_core()


@pytest.fixture
def ctx(tmp_path):
    """`CoreCtx` sintetico per i test: un veicolo, nessun dato reale.

    Il file del taskId punta di proposito a un percorso inesistente: nei test il taskId
    deve arrivare SOLO dal conio via checkPassword, altrimenti si verificherebbe una
    scorciatoia invece della catena vera."""
    from custom_components.omoda9.core.context import CoreCtx

    return CoreCtx(
        vin=FX.VIN, tuserid=FX.TUSERID, pin=FX.PIN, email=FX.EMAIL,
        token_path=str(tmp_path / "token.json"),
        taskid_file=str(tmp_path / "nessun_taskid.txt"),
        tsp_host=FX.TSP_HOST, bff=FX.BFF,
    )


@pytest.fixture
def cloud(monkeypatch, core, ctx):
    """Trasporto cloud finto già installato, con le risposte "tutto ok" di default."""
    fake = FakeCloud().install(monkeypatch)
    fake.on("/tsp/v1/app/auth/login", data={"userToken": FX.USER_TOKEN,
                                            "tUserId": FX.TUSERID})
    fake.on("/tsp/v1/app/vmc/queryList", data=[{"vin": FX.VIN, "nickname": "Auto di prova",
                                                "fullName": "OMODA 9"}])
    fake.on("/tsp/v1/app/vmc/setVecDefault", code="000000")
    fake.on("/tsp/v1/app/cpm/checkPassword", data={"taskId": FX.TASKID})
    # `_access_token` legge il token da disco: lo si serve da un file temporaneo.
    monkeypatch.setattr(core["wake"], "_access_token", lambda _ctx: FX.ACCESS_TOKEN)
    return fake


@pytest.fixture
def config_entry(hass):
    """Config entry già configurato, con dati sintetici (nessun account reale)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    C = OMODA_CONST
    entry = MockConfigEntry(
        domain=C.DOMAIN,
        title=f"Omoda 9 ({FX.VIN})",
        unique_id=FX.VIN,
        data={C.CONF_VIN: FX.VIN, C.CONF_TUSERID: FX.TUSERID,
              C.CONF_EMAIL: FX.EMAIL, C.CONF_PIN: FX.PIN},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def integrazione_avviata(hass, config_entry, cloud, monkeypatch):
    """Integrazione caricata con TUTTO l'I/O esterno neutralizzato.

    Si sostituiscono i tre punti che uscirebbero dal processo: provisioning dei
    certificati (tocca il filesystem), connessione MQTT all'auto (apre un socket TLS
    verso Chery) e i timer periodici (sveglierebbero l'auto). Restano reali le
    piattaforme e la creazione delle entità, che è ciò che si vuole misurare."""
    from custom_components.omoda9.coordinator import Omoda9Coordinator

    # NB (P2-2): qui serviva neutralizzare `_load_core_from_disk`, che a ogni setup
    # ricaricava i moduli core/ creandone una seconda copia e scavalcando i monkeypatch
    # dei test. Con `core/` diventato un sotto-pacchetto vero quel meccanismo non esiste
    # più: è Python a garantire un'unica istanza dei moduli.

    monkeypatch.setattr(Omoda9Coordinator, "_provision_certs",
                        lambda self: (True, "cert finti (test)"))
    monkeypatch.setattr(Omoda9Coordinator, "_connect_car", lambda self: None)
    # i timer contattano il cloud e possono SVEGLIARE l'auto: mai nei test.
    monkeypatch.setattr(Omoda9Coordinator, "async_start_keepalive", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_telemetry_poll", lambda self: None)
    monkeypatch.setattr(Omoda9Coordinator, "async_start_drive_watch", lambda self: None)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    if config_entry.state is not None:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
def token_file(ctx):
    """token.json sintetico su disco, per i test che esercitano refresh/lettura reale."""
    path = pathlib.Path(ctx.token_path)
    path.write_text(FX.token_json(), encoding="utf-8")
    return path
