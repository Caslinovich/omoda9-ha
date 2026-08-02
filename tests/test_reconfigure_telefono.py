"""«Configura»: correggere il numero e CAMBIARE il modo in cui arriva il codice.

Perché questo file esiste. Finché il passo di riconfigurazione toccava il solo PIN mancavano
due vie d'uscita, entrambe incontrate sul campo:

  * chi cambiava numero di telefono continuava a farsi spedire l'SMS al vecchio numero;
  * chi aveva configurato l'integrazione con l'e-mail non poteva passare all'SMS (né
    viceversa), perché la riautenticazione offre **solo il canale con cui l'account è
    configurato**: nel menu compariva «invialo via email» e basta.

In entrambi i casi l'unico rimedio era eliminare e riaggiungere l'integrazione, perdendo
entity_id e storico di oltre cento entità.

⚠️ Il canale attivo è «telefono se c'è un numero, altrimenti e-mail» (`core/session._is_phone`).
È il motivo per cui scegliere l'e-mail deve SVUOTARE il numero: lasciarlo lì continuerebbe a
dirottare l'invio sull'SMS. L'indirizzo invece resta salvato anche scegliendo l'SMS, così
tornare indietro non costa nulla.

⚠️ Tutti i numeri sono sintetici e portano il marcatore richiesto da `check_secrets.sh` sulla
RIGA del valore.
"""
from __future__ import annotations

import pytest
from homeassistant import config_entries

import fixtures as FX
from custom_components.omoda9.const import (
    CONF_AREA_CODE, CONF_EMAIL, CONF_PHONE, CONF_PIN, DOMAIN,
)


@pytest.fixture
async def entry_sms(hass, integrazione_avviata):
    """Trasforma l'entry di prova in un account SMS (registrato col numero)."""
    hass.config_entries.async_update_entry(
        integrazione_avviata,
        data={**integrazione_avviata.data, CONF_EMAIL: "",
              CONF_PHONE: FX.PHONE, CONF_AREA_CODE: FX.AREA_CODE},
    )
    await hass.async_block_till_done()
    return integrazione_avviata


async def _menu(hass, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE,
                         "entry_id": entry.entry_id})


async def _vai(hass, entry, passo):
    r = await _menu(hass, entry)
    return await hass.config_entries.flow.async_configure(
        r["flow_id"], {"next_step_id": passo})


# ───────────────────────────── il menu ─────────────────────────────

async def test_il_menu_offre_sempre_tutti_e_tre_i_rimedi(hass, integrazione_avviata):
    """Anche a un account e-mail va offerto l'SMS: è esattamente chi deve poterci passare."""
    r = await _menu(hass, integrazione_avviata)
    assert r["type"] == "menu"
    assert set(r["menu_options"]) == {
        "reconfigure_pin", "reconfigure_email", "reconfigure_phone"}


async def test_cambiare_canale_non_chiede_il_pin(hass, integrazione_avviata):
    """Il PIN è una credenziale: non può essere pre-riempito, e chiederlo a chi sta solo
    cambiando il modo di ricevere il codice significherebbe pretendere che se lo ricordi."""
    for passo in ("reconfigure_email", "reconfigure_phone"):
        campi = {str(k) for k in (await _vai(hass, integrazione_avviata, passo))
                 ["data_schema"].schema}
        assert CONF_PIN not in campi, passo


# ─────────────────────── passare all'SMS e tornare indietro ───────────────────────

async def test_un_account_email_puo_passare_all_sms(hass, integrazione_avviata):
    """Il caso che ha motivato questo lavoro: dalla notifica di sessione scaduta compariva
    solo «invialo via email», e non c'era modo di scegliere l'SMS."""
    assert not integrazione_avviata.data.get(CONF_PHONE)
    r = await _vai(hass, integrazione_avviata, "reconfigure_phone")
    await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_PHONE: FX.PHONE, CONF_AREA_CODE: FX.AREA_CODE})
    await hass.async_block_till_done()

    assert integrazione_avviata.data[CONF_PHONE] == FX.PHONE
    assert integrazione_avviata.data[CONF_AREA_CODE] == FX.AREA_CODE


async def test_passando_all_sms_l_email_resta_salvata(hass, integrazione_avviata):
    """Così tornare indietro è a due tap invece che una riconfigurazione da capo."""
    prima = integrazione_avviata.data[CONF_EMAIL]
    r = await _vai(hass, integrazione_avviata, "reconfigure_phone")
    await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_PHONE: FX.PHONE, CONF_AREA_CODE: FX.AREA_CODE})
    await hass.async_block_till_done()

    assert integrazione_avviata.data[CONF_EMAIL] == prima


async def test_tornare_all_email_svuota_il_numero(hass, entry_sms):
    """⚠️ Il punto delicato. Il canale attivo si decide sulla presenza del numero: se restasse
    salvato, scegliere «email» non cambierebbe nulla e il codice continuerebbe ad arrivare via
    SMS — un guasto silenzioso, peggio di un errore visibile."""
    r = await _vai(hass, entry_sms, "reconfigure_email")
    await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_EMAIL: "tizio@example.com"})
    await hass.async_block_till_done()

    assert entry_sms.data[CONF_EMAIL] == "tizio@example.com"
    assert not entry_sms.data[CONF_PHONE]
    assert not entry_sms.data[CONF_AREA_CODE]


# ───────────────────────────── correggere il numero ─────────────────────────────

async def test_il_numero_attuale_e_proposto_come_valore_di_partenza(hass, entry_sms):
    """A differenza del PIN: non è una credenziale, e chi entra per cambiare una cifra deve
    vedere da dove parte."""
    schema = (await _vai(hass, entry_sms, "reconfigure_phone"))["data_schema"].schema
    campo = next(k for k in schema if str(k) == CONF_PHONE)
    assert campo.default() == FX.PHONE


async def test_il_numero_passa_dalla_stessa_normalizzazione_del_primo_accesso(hass, entry_sms):
    """Non una seconda copia della pulizia: la stessa. Due copie divergono."""
    r = await _vai(hass, entry_sms, "reconfigure_phone")
    await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_PHONE: "+39 300 987.65-43",       # PHONE_PLACEHOLDER
                       CONF_AREA_CODE: "+39"})
    await hass.async_block_till_done()

    assert entry_sms.data[CONF_PHONE] == "3009876543"          # PHONE_PLACEHOLDER
    assert entry_sms.data[CONF_AREA_CODE] == "39"


async def test_un_numero_impossibile_viene_rifiutato(hass, entry_sms):
    """Meglio un errore nel form che un SMS spedito nel vuoto — o al telefono di un estraneo."""
    prima = entry_sms.data[CONF_PHONE]
    r = await _vai(hass, entry_sms, "reconfigure_phone")
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_PHONE: "12", CONF_AREA_CODE: "39"})

    assert r["errors"]["base"] == "phone_invalid"
    assert entry_sms.data[CONF_PHONE] == prima, "l'entry non va toccato se il dato è rifiutato"


@pytest.mark.parametrize("indirizzo", ["", "   ", "senza-chiocciola", "tizio@", "tizio@dominio"])
async def test_un_indirizzo_impossibile_viene_rifiutato(hass, entry_sms, indirizzo):
    """Senza questo controllo si potrebbe svuotare il numero e restare con un indirizzo
    inutilizzabile: nessuno dei due canali funzionerebbe più."""
    r = await _vai(hass, entry_sms, "reconfigure_email")
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {CONF_EMAIL: indirizzo})

    assert r["errors"]["base"] == "email_invalid"
    assert entry_sms.data[CONF_PHONE], "il numero non va svuotato se l'indirizzo è rifiutato"
