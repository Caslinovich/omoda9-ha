"""Custom component Omoda 9 / Jaecoo — bootstrap.

Sostituisce il bridge standalone (`ha_bridge.py`): la logica MQTT/REST vive in
`coordinator.py`, le entità sono native (niente più MQTT Discovery). Il "cuore di
protocollo" (auth, firma, comandi, sonda) è riusato da `core/` senza riscrivere
la logica già verificata sul campo.

⚠️ SCAFFOLD in costruzione: il config flow (OTP) è attivo; coordinator e platform
entità sono in via di completamento (vedi SHARING_TODO.md → roadmap component).
"""
from __future__ import annotations

import logging
import os
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

# Vendor del "cuore di protocollo": i moduli in core/ si importano tra loro per
# nome (import wake / import omoda_auth as A …) → aggiungo core/ al path una volta.
_CORE = os.path.join(os.path.dirname(__file__), "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# Cancella la cache di bytecode di core/ all'import. Un update HACS sovrascrive i .py ma lascia
# il vecchio __pycache__: siccome i moduli core/ si importano per nome nudo, Python può
# continuare a caricare quel bytecode stale e far girare il codice VECCHIO dopo l'aggiornamento.
# Farlo qui (prima che i moduli core/ vengano importati) forza una ricompilazione dal sorgente
# attuale. Best-effort: qualunque errore (FS read-only, permessi, race) è ignorabile.
try:
    import shutil as _shutil
    _pyc = os.path.join(_CORE, "__pycache__")
    if os.path.isdir(_pyc):
        _shutil.rmtree(_pyc, ignore_errors=True)
except Exception:  # noqa: BLE001
    pass

# Moduli core/ in ordine di dipendenza (prima le dipendenze): così, caricandoli in quest'ordine,
# ognuno risolve i propri import incrociati sui moduli appena caricati.
_CORE_MODULES = (
    "codes", "omoda", "omoda_auth", "tsp_sign", "captcha_solver", "prova_token",
    "login_omoda", "wake", "session", "probe", "provision", "commands",
)


def _load_core_from_disk() -> None:
    """Carica i moduli core/ DI QUESTA integrazione dai loro file e li fissa in sys.modules.
    Protegge da tre situazioni che finiscono tutte allo stesso modo (button.py fa `import
    commands` e si ritrova il catalogo SBAGLIATO, cioè codice vecchio o di un altro):

      1. bytecode stale — un update HACS lascia il vecchio __pycache__ (già ripulito sopra);
      2. sys.modules stale — a un reload dell'entry i moduli restano quelli del primo import;
      3. COLLISIONE DI NOMI — i moduli core/ usano nomi nudi e generici (`commands`, `wake`,
         `session`, `codes`…): un `commands.py` di un'ALTRA integrazione sul path potrebbe
         vincere l'import. `importlib.reload()` non salva (ricaricherebbe quello estraneo).

    spec_from_file_location(nome, core/<nome>.py) carica il NOSTRO file esatto, ricompilato, e lo
    fissa in sys.modules PRIMA che le piattaforme lo importino. Best-effort; è bloccante → gira
    in executor. Sicuro qui: il setup avviene dopo l'eventuale unload precedente."""
    import importlib.util
    for name in _CORE_MODULES:
        path = os.path.join(_CORE, f"{name}.py")
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module   # fissa il NOSTRO prima dell'exec: gli import incrociati risolvono qui
            spec.loader.exec_module(module)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Omoda9: impossibile caricare da disco il modulo core %s: %s", name, err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inizializza l'integrazione da un config entry."""
    # Fissa i moduli core/ (catalogo comandi, protocollo) dai file di QUESTA integrazione PRIMA
    # che coordinator/piattaforme li importino per nome nudo → né un reload, né una cache di
    # bytecode stale, né una collisione di nomi possono servire il catalogo vecchio.
    await hass.async_add_executor_job(_load_core_from_disk)

    from .coordinator import Omoda9Coordinator

    coordinator = Omoda9Coordinator(hass, entry)

    # FASE 3c: i cert mutual-TLS devono esserci PRIMA di connettere l'MQTT auto.
    ok, detail = await coordinator.async_provision_certs()
    if not ok:
        raise ConfigEntryNotReady(detail)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # stato sessione iniziale + avvio connessione MQTT all'auto
    await coordinator.async_check_session()
    # [H4] se QUALSIASI passo dell'avvio fallisce (connect MQTT, avvio timer, forward
    #      delle piattaforme) ripuliamo TUTTE le risorse già avviate — client paho e
    #      timer keepalive/poll — e togliamo il coordinator da hass.data, così non
    #      restano thread/timer orfani; poi rilanciamo → HA ritenta il setup.
    try:
        await coordinator.async_start()
        # keep-alive: refresh sessione periodico per non far scadere il token da fermi
        coordinator.async_start_keepalive()
        # poll telemetria periodico (sveglia + lettura); intervalli dalle opzioni
        coordinator.async_start_telemetry_poll()
        # battito di rilevamento marcia (sola lettura): fa partire il refresh automatico durante un
        # viaggio. No-op se l'interruttore "Aggiornamento automatico" è spento (lo riavvia lo switch).
        coordinator.async_start_drive_watch()
        # ricarica l'entry quando l'utente cambia le opzioni (es. intervalli di poll)
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # backfill identità veicolo (nome device dinamico) per gli entry creati prima che il
        # config flow la salvasse: in background, così un eventuale reload avviene a setup finito.
        hass.async_create_background_task(
            coordinator.async_ensure_vehicle_identity(), "omoda9_vehicle_identity")
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await hass.async_add_executor_job(coordinator.async_stop)
        raise
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opzioni cambiate → ricarica l'entry per riapplicare gli intervalli di poll."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica l'integrazione."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # [MED] solo se l'unload delle piattaforme è riuscito smontiamo il coordinator: se
    #       una piattaforma rifiuta l'unload (ok=False) HA considera l'entry ancora
    #       caricato → non distruggiamo il coordinator sotto entità ancora vive (stato
    #       coerente; HA ritenterà l'unload).
    if ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            # async_stop è bloccante (loop_stop fa join del thread paho) → executor.
            await hass.async_add_executor_job(coordinator.async_stop)
    return ok
