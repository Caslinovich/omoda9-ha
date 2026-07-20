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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

# P2-2: il "cuore di protocollo" è ora il sotto-pacchetto `.core`, importato normalmente
# (`from .core import commands`). Sono spariti — e con loro un'intera classe di problemi:
#
#   * `sys.path.insert(core/)`: inquinava il path dell'intero processo Home Assistant,
#     esponendo nomi generici (`commands`, `session`, `wake`) alle collisioni con altre
#     integrazioni;
#   * la cancellazione del `__pycache__` a ogni import e il ricaricamento da disco a ogni
#     setup: servivano solo perché i nomi nudi rendevano ambiguo QUALE modulo si stesse
#     caricando. Con gli import di pacchetto è Python a garantirlo, e l'aggiornamento
#     HACS invalida la cache da sé (i .pyc sono indicizzati per percorso completo).
#
# Effetto collaterale utile: i logger dei moduli core/ ora rispondono a `manifest.loggers`.


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inizializza l'integrazione da un config entry."""
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
    """Ricarica l'entry SOLO se sono cambiate davvero le opzioni.

    `add_update_listener` scatta a ogni `async_update_entry`, anche quando a cambiare è
    `entry.data` e non le opzioni. Due conseguenze, entrambe reali:

    * il backfill dell'identità veicolo (task in background avviato dal setup) scrive in
      `entry.data` → l'entry appena avviata veniva **subito ricaricata**. Al primo avvio
      HA la caricava due volte, e se lo spegnimento arrivava mentre il reload era in volo
      il task restava appeso oltre la fase di chiusura (HA lo segnala: «Integrations
      should cancel non-critical tasks … to prevent delaying shutdown») lasciando l'entry
      in UNLOAD_IN_PROGRESS;
    * i percorsi che cambiano il PIN (Repair e riconfigura) si ricaricano **già da soli**
      in modo esplicito → il listener aggiungeva un secondo reload inutile.

    Chi ha davvero bisogno del reload è solo l'options flow (intervalli di poll, override
    del nome), che non ricarica per conto suo. Si confronta quindi con la fotografia delle
    opzioni applicate dal coordinator vivo. Se il coordinator non c'è (entry non ancora in
    `hass.data`) si ricarica, che è il comportamento prudente di prima.

    Si usa `async_schedule_reload` invece di attendere `async_reload`: il listener non
    resta appeso ad attendere il reload di se stesso, ed è HA a possedere e cancellare il
    task allo spegnimento.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and dict(entry.options or {}) == coordinator.applied_options:
        return
    hass.config_entries.async_schedule_reload(entry.entry_id)


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
        # P1-4/P2-6: qui si ripulivano `OMODA_PIN` e `OMODA_EMAIL` da `os.environ`, dove il
        # config flow li scriveva per passarli ai moduli core/. Non serve più — ed è la
        # garanzia più forte: con il contesto per-chiamata quei segreti nell'ambiente del
        # processo Home Assistant **non ci finiscono mai**, quindi non c'è nulla da
        # ripulire. (L'unico uso legittimo dell'ambiente resta quello EFFIMERO dei
        # sottoprocessi di login, che vive e muore con la singola chiamata.)
    return ok
