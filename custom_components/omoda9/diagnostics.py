"""Diagnostica scaricabile dell'integrazione Omoda 9 / Jaecoo.

Genera il report che HA offre con «Scarica diagnostica» nella pagina
dell'integrazione. Pensato per il SUPPORTO: contiene stato sessione, parametri
di regione, presenza di token/certificati e l'ultima telemetria ricevuta, ma
NON espone alcun dato personale o segreto:

  • email, PIN, VIN, tUserId            → oscurati (REDACTED)
  • numero di telefono                  → oscurato, restano le ultime 4 cifre
  • posizione GPS (lat/lon)             → oscurata (dove vivi non esce mai)
  • token e certificati mutual-TLS      → solo «presente: sì/no», mai il contenuto

Gli indirizzi e-mail spariscono in DUE forme: quella grezza e quella già mascherata alla
sorgente (`m***@dominio.it`, che nel dialogo a schermo è voluta perché conferma all'utente
dove sta andando il codice). In questo file non resta nemmeno il dominio.

Così l'utente può inviarti il file in tutta sicurezza.
"""
from __future__ import annotations

import os
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CERT_FILES
from .core import mask

# Chiavi da oscurare ovunque compaiano (config entry + eventuali dict annidati).
# NB: «seq» sta qui perché nel payload realtime vale "<VIN>-<timestamp>" → contiene il VIN.
# NB: «certs_src» è il PERCORSO da cui l'utente ha importato i certificati mutual-TLS: è
# info-disclosure sul filesystem (nome utente, struttura delle cartelle, a volte un backup
# dell'app) e non serve al supporto → oscurato (P1-6).
# NB: «phone»/«area_code»/«mobile» = identità di login degli account registrati col numero
# (login via SMS). Sono dato personale quanto l'email — e a differenza di un OTP non scadono
# mai. ⚠️ Oscurare la CHIAVE non basta: il numero compare anche dentro frasi discorsive
# (`session_detail`), dove non è una chiave ma testo libero → lì si maschera alla sorgente,
# in core/session.py. Questa deny-list copre solo il ramo entry.data/options.
TO_REDACT = {
    "email", "pin", "vin", "tuserid", "seq", "certs_src",
    "phone", "area_code", "mobile",
    "lat", "lon", "latitude", "longitude", "position",
}


def _scrub_valore(obj: Any, ago: str) -> Any:
    """Toglie `ago` ovunque compaia come SOTTOSTRINGA, a qualsiasi profondità.

    Generalizzazione di `_scrub_vin`: serve per i dati che compaiono anche **dentro frasi**,
    non solo come valore di una chiave nota. Il caso concreto è il numero di telefono degli
    account SMS, che `core/session.py` scrive dentro `session_detail` («Codice inviato al
    numero …») — un campo esportato verbatim, dove `TO_REDACT` per definizione non arriva.
    Il numero è già mascherato alla sorgente: questa è la rete di sicurezza per i percorsi
    che non passano di lì (dati vecchi rimasti in memoria, campi aggiunti in futuro)."""
    if not ago:
        return obj
    if isinstance(obj, dict):
        return {k: _scrub_valore(v, ago) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_valore(v, ago) for v in obj]
    if isinstance(obj, str) and ago in obj:
        return obj.replace(ago, "**REDACTED**")
    return obj


def _scrub_vin(obj: Any, vin: str) -> Any:
    """Rete di sicurezza storica sul VIN: ora un caso particolare di `_scrub_valore`.
    Il nome resta perché è quello usato nei punti di chiamata e nei test."""
    return _scrub_valore(obj, vin)


def _scrub_email(obj: Any) -> Any:
    """Sostituisce QUALUNQUE indirizzo e-mail con `**EMAIL**`, ovunque compaia dentro una
    stringa del report.

    Perché serve nonostante `TO_REDACT` contenga già `email`: la deny-list lavora per CHIAVE,
    e l'indirizzo compariva dentro una frase (`session_detail`). Stesso identico difetto già
    visto con le coordinate e col numero di telefono — terza volta, stesso schema. Il pattern
    è quello unico di `core/mask.py`, condiviso col monitor diagnostico.

    ⚠️ SI CANCELLA ANCHE LA FORMA GIÀ MASCHERATA (`m***@dominio.it`). Non è ridondanza: quella
    forma è voluta nel dialogo che l'utente legge — gli conferma che il codice sta andando dove
    deve — ma in un file che finisce su GitHub il dominio è comunque un'informazione su di lui.
    Mascherare alla sorgente e fermarsi lì era un peggioramento rispetto a prima, quando
    l'indirizzo grezzo veniva sostituito per intero: il canale a schermo e il canale pubblico
    vogliono cose diverse, e questa è la riga in cui si separano."""
    if isinstance(obj, dict):
        return {k: _scrub_email(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_email(v) for v in obj]
    if isinstance(obj, str):
        return mask.RE_EMAIL_MASCHERATA.sub("**EMAIL**", mask.RE_EMAIL.sub("**EMAIL**", obj))
    return obj


def _scrub_geo(obj: Any) -> Any:
    """Toglie le coordinate ovunque compaiano DENTRO UNA STRINGA (2026-07-20).

    `TO_REDACT` copre `lat`/`lon` quando sono chiavi di un dizionario. Non copriva però
    il caso reale trovato sul campo: `probe_status` è un messaggio discorsivo destinato
    all'utente e conteneva «lat=40.90…, lon=14.34…» — le coordinate della macchina
    finivano quindi in chiaro proprio nel file che l'intestazione di questo modulo
    promette essere «sicuro da inviare».

    È lo stesso difetto già corretto nel monitor diagnostico, e si riusa apposta lo
    STESSO pattern: due implementazioni separate della stessa regola divergono, e la
    seconda copia sarebbe quella dimenticata.
    """
    from .diag import scrub_coordinates   # stdlib-only, import sicuro

    if isinstance(obj, dict):
        return {k: _scrub_geo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_geo(v) for v in obj]
    if isinstance(obj, str):
        return scrub_coordinates(obj)
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Report diagnostico per un config entry (richiamato da «Scarica diagnostica»)."""
    diag: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            # titolo forzato senza VIN (il titolo reale è "Omoda 9 (<VIN>)")
            "title": "Omoda 9",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            # anche le options passano dalla redazione: oggi contengono solo intervalli di
            # polling, ma così una chiave sensibile aggiunta domani è già coperta.
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
    }

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        diag["coordinator"] = "non inizializzato (entry non caricato)"
        return diag

    # Presenza dei file sensibili come semplici booleani — mai il loro contenuto.
    token_present = await hass.async_add_executor_job(
        os.path.isfile, coordinator.token_path
    )
    certs_present: dict[str, bool] = {}
    for fname in CERT_FILES:
        path = os.path.join(coordinator.certs_dir, fname)
        certs_present[fname] = await hass.async_add_executor_job(os.path.isfile, path)

    data = dict(coordinator.data or {})
    has_position = bool(data.get("position"))
    vin = getattr(coordinator, "vin", "") or ""
    # La posizione GPS è sensibile (dove abiti) → mai esportata, neanche oscurata coord-per-coord.
    realtime = data.get("realtime")
    if isinstance(realtime, dict):
        realtime = _scrub_vin(async_redact_data(realtime, TO_REDACT), vin)
    # Telemetria 5A02 (stato porte/clima/sedili…): redazione per chiave + passata anti-VIN.
    fields = data.get("fields")
    if isinstance(fields, dict):
        fields = _scrub_vin(async_redact_data(dict(fields), TO_REDACT), vin)

    diag["coordinator"] = {
        "region": {
            "bff": coordinator.bff,
            "tsp_host": coordinator.tsp_host,
            "car_mqtt_host": coordinator.car_host,
            "car_mqtt_port": coordinator.car_port,
            "channel_id": coordinator.channel_id,
        },
        "poll": {
            "normal_min": coordinator.poll_normal_min,
            "charging_min": coordinator.poll_charging_min,
            "enabled": coordinator.poll_enabled,
        },
        "token_present": token_present,
        "certs_present": certs_present,
        "state": {
            "session_ok": data.get("session_ok"),
            "session_detail": data.get("session_detail"),
            "awake": data.get("awake"),
            "car_connected": data.get("car_connected"),
            "has_position_fix": has_position,
            "last_seen": data.get("last_seen"),
            "last_wake": data.get("last_wake"),
            "last_pos_fix": data.get("last_pos_fix"),
            "cmd_status": data.get("cmd_status"),
            "wake_status": data.get("wake_status"),
            "probe_status": data.get("probe_status"),
            "realtime": realtime,
            "fields_count": len(data.get("fields") or {}),
            "fields": fields,
        },
    }

    # Monitor diagnostico (diag.py), presente solo se attivo: ring buffer + contatori.
    # Gli eventi sono GIÀ redatti alla cattura; qui passano comunque dalla redazione
    # standard — difesa in profondità, come per realtime/fields sopra.
    recorder = getattr(coordinator, "_diag", None)
    if recorder is not None:
        snap = recorder.snapshot()
        diag["diagnostic_mode"] = _scrub_vin(async_redact_data(snap, TO_REDACT), vin)

    # Passate FINALI su TUTTO il report, in fondo e una volta sola. Stanno qui di proposito:
    # applicarle ai singoli campi significherebbe ricordarsi di farlo per ognuno — ed è
    # esattamente la dimenticanza che ha fatto uscire la posizione dentro `probe_status`, un
    # messaggio discorsivo che nessuna deny-list per chiave poteva coprire. Qui non c'è nulla
    # da ricordare: ciò che esce dal modulo è già passato di qui.
    #   * coordinate (2026-07-20)
    #   * numero di telefono (2026-08-02): stesso identico difetto, altro dato — compariva
    #     dentro `session_detail` («Codice inviato al numero …»). Mascherato anche alla
    #     sorgente in core/session.py; questa è la rete sotto.
    #   * indirizzo e-mail (2026-08-02): l'intestazione di questo file prometteva «email →
    #     oscurata» mentre `session_detail` la conteneva per esteso («Codice inviato alla mail
    #     …»), perché la deny-list lavora per CHIAVE e lì l'indirizzo sta dentro una frase.
    #     Mascherato alla sorgente in core/session.py; questa passata prende anche gli
    #     indirizzi che dovessero arrivare da canali non nostri (messaggi d'errore del server).
    #
    # ⚠️ L'ORDINE CONTA, e va letto da destra a sinistra: l'e-mail per PRIMA. Tutti i marcatori
    # di redazione contengono asterischi (`**REDACTED**`, `**GEO**`), e un asterisco non fa
    # parte dei caratteri ammessi prima della `@`: se una passata precedente tocca la parte
    # locale di un indirizzo — succede quando ci si trova dentro il numero di telefono o il VIN
    # — quello che resta non è più riconoscibile come e-mail e sfugge del tutto. Misurato:
    # `utente mario3001234567@dominio.it` diventava `mario**REDACTED**@dominio.it`, col dominio
    # in chiaro, invece di `**EMAIL**`.
    return _scrub_valore(_scrub_geo(_scrub_email(diag)),
                         getattr(coordinator, "phone", "") or "")
