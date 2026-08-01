"""Mappatura della telemetria: dagli envelope MQTT dell'auto allo stato in HA.

Qui non ci sono bug noti da bloccare — il parsing è la parte che ha sempre funzionato.
Il valore è un altro: fissare il contratto con il backend. Se un giorno Chery cambia la
forma dei messaggi, questi test lo dicono subito, con un envelope sotto gli occhi,
invece di lasciare i sensori fermi al giorno prima senza alcun errore nel log.
"""
from __future__ import annotations

import fixtures as FX


class _Msg:
    """Il minimo che `_on_car_message` si aspetta da un messaggio paho."""

    def __init__(self, payload: dict) -> None:
        import json
        self.payload = json.dumps(payload).encode()
        self.topic = "app/1/test/account/msgCenter/msg"


async def _consegna(hass, coordinator, envelope: dict) -> None:
    """Consegna un envelope come farebbe il thread paho e attende la propagazione."""
    coordinator._on_car_message(None, None, _Msg(envelope))
    await hass.async_block_till_done()


def _coordinator(hass, entry):
    from custom_components.omoda9.const import DOMAIN
    return hass.data[DOMAIN][entry.entry_id]


async def test_5a02_popola_i_campi(hass, integrazione_avviata):
    """Il push di telemetria riempie `fields` e marca l'auto come sveglia."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02(frontLeftDoor="1", doorLock="1"))

    campi = coord.data["fields"]
    assert campi["frontLeftDoor"] == "1"
    assert campi["doorLock"] == "1"
    assert coord.data["awake"] is True
    assert coord.data["last_seen"] is not None


async def test_il_campo_time_non_diventa_uno_stato(hass, integrazione_avviata):
    """`time` è il timestamp dell'envelope, non uno stato del veicolo."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02())
    assert "time" not in coord.data["fields"]


async def test_meta_di_conferma_fuori_dai_campi(hass, integrazione_avviata):
    """Una conferma comando porta `result`/`seq`/`resultTime`: sono meta del comando,
    non telemetria. I campi di STATO che l'accompagnano invece devono entrare."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.cmd_confirm(result="1"))

    campi = coord.data["fields"]
    for meta in ("result", "resultTime", "seq", "reason", "hasAsy"):
        assert meta not in campi, f"meta di conferma finito fra i campi: {meta}"
    assert campi["doorLock"] == "1", "i campi di stato della conferma devono entrare"


async def test_esito_conferma_leggibile(hass, integrazione_avviata):
    """L'esito mostrato all'utente distingue eseguito / in corso / riuscito a metà.

    `reason` valorizzato = qualche modulo non ha eseguito, e vince su qualunque `result`:
    è l'unico campo che l'auto popola solo quando qualcosa è andato storto."""
    coord = _coordinator(hass, integrazione_avviata)

    await _consegna(hass, coord, FX.cmd_confirm(result="1"))
    assert "✅" in coord.data["cmd_status"]

    await _consegna(hass, coord, FX.cmd_confirm(result="5"))
    assert "⏳" in coord.data["cmd_status"]

    await _consegna(hass, coord, FX.cmd_confirm(result="1", reason=["door_open"]))
    esito = coord.data["cmd_status"]
    assert "✅" not in esito, "un guasto non deve apparire come successo"
    assert "in parte" in esito


async def test_esito_parziale_nomina_i_moduli(hass, integrazione_avviata):
    """Il `reason` reale della macro comfort diventa una frase, non un dump Python.

    Forma vista in campo: una voce per centralina, `modelId` 0 = clima, 9 = sedile guida
    ventilato (isolato dal comando singolo) e 10/11/13 gli altri tre. L'utente deve leggere
    QUALI moduli hanno fatto storie; i codici grezzi restano in coda perché sono l'unico
    appiglio diagnostico. Un `modelId` fuori tabella non va inventato: si riporta com'è."""
    coord = _coordinator(hass, integrazione_avviata)
    reason = [{"code": "11", "modelId": "0"}, {"code": "1", "modelId": "9"},
              {"code": "1", "modelId": "10"}, {"code": "1", "modelId": "77"}]
    await _consegna(hass, coord, FX.cmd_confirm(result="1", reason=reason))

    esito = coord.data["cmd_status"]
    assert "clima" in esito
    assert "sedile guida ventilato" in esito
    assert "modulo 77" in esito, "un modulo sconosciuto si riporta grezzo, non si indovina"
    assert "0:11" in esito, "i codici grezzi servono alla diagnosi: non vanno persi"
    assert len(esito) <= 255, "lo stato di un sensore HA non può superare i 255 caratteri"


async def test_esito_nomina_il_sedile_guida_riscaldato(hass, integrazione_avviata):
    """`modelId` 4 = riscaldamento del sedile guida, non «modulo 4».

    Distinto il 2026-08-01 isolando il comando singolo: inviando il solo riscaldamento del
    sedile guida l'auto ha risposto esattamente `[0:9, 4:1]`. Le macro non lo permettevano
    (lì i quattro sedili compaiono sempre insieme)."""
    coord = _coordinator(hass, integrazione_avviata)
    reason = [{"code": "9", "modelId": "0"}, {"code": "1", "modelId": "4"}]
    await _consegna(hass, coord, FX.cmd_confirm(result="3", reason=reason))

    esito = coord.data["cmd_status"]
    assert "sedile guida riscaldato" in esito
    assert "modulo 4" not in esito
    assert "in parte" in esito, "un sedile che non parte resta un'esecuzione parziale"


async def test_solo_il_clima_non_e_un_guasto(hass, integrazione_avviata):
    """Se l'unico modulo segnalato è il clima, niente avviso di problema.

    Falso allarme sistematico corretto il 2026-08-01: il codice 95 sul clima arriva su
    praticamente ogni comando di SPEGNIMENTO, compresi quelli eseguiti alla perfezione.
    Chi spegneva il clima leggeva «Eseguito solo in parte ⚠️» senza che nulla fosse andato
    storto. I codici grezzi restano comunque nel messaggio, per la diagnosi."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord,
                    FX.cmd_confirm(result="3", reason=[{"code": "95", "modelId": "0"}]))

    esito = coord.data["cmd_status"]
    assert "in parte" not in esito, "il solo clima non è un'esecuzione parziale"
    assert "⚠️" not in esito
    assert "0:95" in esito, "il codice grezzo resta: serve alla diagnosi"

    # ma basta UN modulo vero accanto perché torni l'avviso
    await _consegna(hass, coord, FX.cmd_confirm(
        result="3", reason=[{"code": "95", "modelId": "0"}, {"code": "1", "modelId": "9"}]))
    assert "in parte" in coord.data["cmd_status"]


async def test_esito_parziale_regge_un_reason_deforme(hass, integrazione_avviata):
    """Se il backend cambia la forma di `reason`, meglio il grezzo che un'eccezione:
    questo codice gira nel thread paho, dove sollevare significa perdere il messaggio."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.cmd_confirm(result="1", reason="boh"))
    assert "boh" in coord.data["cmd_status"]


async def test_posizione_solo_dal_push_1301(hass, integrazione_avviata):
    """La posizione si riconosce dal TIPO di messaggio (1301), non dalla sola presenza
    di lat/lon: un 5A02 che per caso li contenesse non deve spostare il device_tracker."""
    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.position_1301(lat=45.07, lon=7.68))

    assert coord.data["position"]["lat"] == "45.07"
    assert coord.data["last_pos_fix"] is not None

    # un 5A02 con lat/lon "di contrabbando" non deve essere trattato come posizione
    prima = coord.data["last_pos_fix"]
    await _consegna(hass, coord, FX.telemetry_5a02(lat="1.0", lon="2.0"))
    assert coord.data["position"]["lat"] == "45.07"
    assert coord.data["last_pos_fix"] == prima


async def test_solo_i_campi_geo_entrano_nella_posizione(hass, integrazione_avviata):
    """In `position` va SOLO la geolocalizzazione: batteria e simili vivono altrove."""
    coord = _coordinator(hass, integrazione_avviata)
    envelope = FX.position_1301()
    envelope["content"]["data"]["dumpEnergy"] = "72"
    await _consegna(hass, coord, envelope)
    assert "dumpEnergy" not in coord.data["position"]


async def test_payload_illeggibile_non_rompe_nulla(hass, integrazione_avviata):
    """Un messaggio corrotto deve essere ignorato: gira nel thread paho, un'eccezione
    lì dentro ucciderebbe la ricezione di tutti i messaggi successivi."""
    coord = _coordinator(hass, integrazione_avviata)

    class Rotto:
        payload = b"\xff\xfe non json"
        topic = "x"

    coord._on_car_message(None, None, Rotto())     # non deve sollevare
    await hass.async_block_till_done()
    assert coord.data is not None


async def test_la_posizione_non_genera_campi_sconosciuti(hass, integrazione_avviata):
    """Regressione del 2026-07-20, lato coordinator.

    La ricerca dei campi non mappati confronta le chiavi con `META`, che descrive la
    telemetria di STATO (5A02). Girava però su OGNI messaggio: su un push di posizione
    (1301) segnalava quindi `lat`/`lon` come "campi da mappare" — falso, sono già
    gestiti — e nel farlo ne registrava il VALORE come campione, mandando le coordinate
    dell'auto nel file diagnostico."""
    coord = _coordinator(hass, integrazione_avviata)

    visti: list[tuple] = []

    class FintoMonitor:
        def note_unknown_field(self, key, value, svc):
            visti.append((key, value, svc))

        def record(self, *a, **kw):
            pass

    coord._diag = FintoMonitor()
    try:
        await _consegna(hass, coord, FX.position_1301(lat=40.906483, lon=14.351322))
        assert visti == [], f"la posizione ha generato campi sconosciuti: {visti}"

        # un 5A02 con un campo davvero nuovo DEVE invece essere segnalato: è la
        # funzione che serve a scoprire autonomia/pressione gomme.
        await _consegna(hass, coord, FX.telemetry_5a02(rangeKm="215"))
        assert any(k == "rangeKm" for k, _v, _s in visti), \
            "un campo davvero nuovo del 5A02 non è stato segnalato"
        assert not any(k in ("lat", "lon") for k, _v, _s in visti)
    finally:
        coord._diag = None


async def test_i_flag_unita_non_sporcano_la_scoperta(hass, integrazione_avviata):
    """I campi che finiscono in `Unit` sono marcatori di unità di misura (valgono sempre
    1 o 2), non valori: non devono comparire fra i "campi da scoprire", altrimenti
    nascondono nel rumore gli eventuali campi VERI ancora da mappare (trovato in campo il
    2026-07-20: rangeUnit/averageFuelUnit/tirePressureUnit/avgHkPowerUnit segnalati a vuoto)."""
    coord = _coordinator(hass, integrazione_avviata)
    visti: list[str] = []

    class FintoMonitor:
        def note_unknown_field(self, key, value, svc):
            visti.append(key)

        def record(self, *a, **kw):
            pass

    coord._diag = FintoMonitor()
    try:
        await _consegna(hass, coord, FX.telemetry_5a02(
            rangeUnit="1", averageFuelUnit="1", tirePressureUnit="1", avgHkPowerUnit="2",
            rangeKm="215"))
        assert not any(k.endswith("Unit") for k in visti), \
            f"flag-unità segnalati come campi da scoprire: {[k for k in visti if k.endswith('Unit')]}"
        assert "rangeKm" in visti, "il campo vero accanto ai flag deve restare segnalato"
    finally:
        coord._diag = None


async def test_serratura_zero_e_bloccata(hass, integrazione_avviata):
    """Convenzione verificata dal vivo (2026-06-17): doorLock 0 = Bloccata, 1 = Sbloccata.

    Era invertita in origine. Un'inversione qui è particolarmente insidiosa: la
    dashboard mostrerebbe "aperta" un'auto chiusa, o peggio il contrario."""
    from custom_components.omoda9.entity import field_on

    coord = _coordinator(hass, integrazione_avviata)
    await _consegna(hass, coord, FX.telemetry_5a02(doorLock="0"))
    assert coord.data["fields"]["doorLock"] == "0"
    assert field_on("0") is False
    assert field_on("1") is True
