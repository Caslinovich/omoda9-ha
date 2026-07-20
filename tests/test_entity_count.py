"""P2-9 — invariante «105 entità»: la regressione più facile da introdurre senza accorgersene.

Il conteggio delle entità è tracciato a mano nelle note di progetto e cambia a ogni
release. Il modo tipico in cui si rompe è silenzioso: si aggiunge un comando al catalogo
`core/commands.py` e — se non finisce anche in `COMMANDS_AS_RICH_ENTITY` — compare un
pulsante in più che nessuno ha chiesto. Nessun errore, nessun log: solo un'entità nuova.

Due livelli, di proposito:

  1. **aritmetica sulle liste sorgenti** — non serve avviare HA, e quando fallisce dice
     *quale* lista è cambiata invece che «erano 105, sono 106»;
  2. **conteggio reale a integrazione avviata** — l'unico che verifica davvero che le
     piattaforme creino ciò che si crede.
"""
from __future__ import annotations

import pytest

from custom_components.omoda9.const import (
    COMMANDS_AS_RICH_ENTITY,
    FIELDS_AS_RICH_ENTITY,
    PLATFORMS,
)

# Ripartizione attesa, verificata dal vivo (v1.5.24, 2026-07-06 → 105 entità, 0 unavailable).
# Modificare questi numeri è una DECISIONE: va fatto insieme al changelog e alle note.
ATTESO = {
    "binary_sensor": 26,
    "sensor": 38,
    "button": 14,
    "switch": 17,
    "cover": 3,
    "number": 2,
    "climate": 1,
    "lock": 1,
    "device_tracker": 1,
    "text": 1,
    "time": 1,
}
TOTALE_ATTESO = 105


def test_totale_dichiarato_coerente():
    """Il totale e la ripartizione devono raccontare la stessa storia."""
    assert sum(ATTESO.values()) == TOTALE_ATTESO


def test_ogni_piattaforma_e_coperta():
    """Una piattaforma nuova senza numero atteso passerebbe inosservata."""
    assert set(PLATFORMS) == set(ATTESO), (
        f"piattaforme senza conteggio atteso: {set(PLATFORMS) ^ set(ATTESO)}"
    )


# ───────────────────────── livello 1: aritmetica sulle liste sorgenti ─────────────────────────
def test_sensori_da_campi_auto(core):
    """`SENSORS` filtrata per componente, meno i campi promossi a entità "ricche"."""
    from custom_components.omoda9.coordinator import SENSORS

    sensor = [s for s in SENSORS
              if s["comp"] == "sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY]
    binary = [s for s in SENSORS
              if s["comp"] == "binary_sensor" and s["key"] not in FIELDS_AS_RICH_ENTITY]
    assert len(sensor) == 3, [s["key"] for s in sensor]
    assert len(binary) == 15, [s["key"] for s in binary]


def test_nessun_campo_ricco_orfano():
    """Ogni chiave in `FIELDS_AS_RICH_ENTITY` deve esistere in `SENSORS`.

    Un refuso qui non darebbe errore: il filtro semplicemente non escluderebbe nulla e
    comparirebbe un sensore doppione accanto all'entità ricca."""
    from custom_components.omoda9.coordinator import SENSORS

    chiavi = {s["key"] for s in SENSORS}
    orfane = FIELDS_AS_RICH_ENTITY - chiavi
    assert not orfane, f"chiavi in FIELDS_AS_RICH_ENTITY che non esistono in SENSORS: {orfane}"


def test_pulsanti_dal_catalogo_comandi(core):
    """Il punto di rottura più probabile dell'invariante.

    Un comando aggiunto al catalogo che non finisce in `COMMANDS_AS_RICH_ENTITY` crea
    un pulsante in più. Asserire QUI dà un messaggio di errore che indica il colpevole."""
    commands = core["commands"]
    catalogo = {k for k, _ in commands.COMMANDS}

    orfani = COMMANDS_AS_RICH_ENTITY - catalogo
    assert not orfani, f"comandi 'ricchi' che non esistono nel catalogo: {orfani}"

    pulsanti = catalogo - COMMANDS_AS_RICH_ENTITY
    assert len(pulsanti) == 9, (
        f"i pulsanti generati dal catalogo sono {len(pulsanti)}, attesi 9. "
        f"Se hai aggiunto un comando, valuta se va in COMMANDS_AS_RICH_ENTITY "
        f"(lock/switch/cover) o se è davvero un pulsante nuovo. Attuali: {sorted(pulsanti)}"
    )


def test_campi_unita_non_diventano_sensori():
    """`rangeUnit`/`averageFuelUnit`/`tirePressureUnit` valgono SEMPRE "1": sono flag di
    unità di misura, non valori. Mapparli mostrerebbe un sensore fisso a 1 — errore già
    fatto una volta, quindi vale la pena bloccarlo."""
    from custom_components.omoda9.coordinator import META

    for flag in ("rangeUnit", "averageFuelUnit", "tirePressureUnit"):
        assert flag not in META, f"{flag} è un flag di unità, non deve diventare un sensore"


# ───────────────────────── livello 2: conteggio reale ─────────────────────────
async def test_conteggio_entita_reale(hass, integrazione_avviata):
    """Le entità davvero registrate da HA, per piattaforma.

    È il test che vale: gli altri controllano le liste sorgenti, questo controlla il
    risultato. Se fallisce, il messaggio mostra la differenza piattaforma per piattaforma."""
    conteggio: dict[str, int] = {}
    for entity_id in hass.states.async_entity_ids():
        dominio, _, oggetto = entity_id.partition(".")
        if oggetto.startswith("omoda9_"):
            conteggio[dominio] = conteggio.get(dominio, 0) + 1

    differenze = {p: (conteggio.get(p, 0), ATTESO[p])
                  for p in ATTESO if conteggio.get(p, 0) != ATTESO[p]}
    assert not differenze, f"(trovate, attese) per piattaforma: {differenze}"
    assert sum(conteggio.values()) == TOTALE_ATTESO


async def test_nessuna_entita_duplicata(hass, integrazione_avviata):
    """Un `unique_id` ripetuto fa scartare l'entità in silenzio: si vedrebbe solo come
    un conteggio più basso del previsto."""
    from homeassistant.helpers import entity_registry as er

    registro = er.async_get(hass)
    unici = [e.unique_id for e in registro.entities.values()]
    doppi = {u for u in unici if unici.count(u) > 1}
    assert not doppi, f"unique_id duplicati: {doppi}"
