"""Riconfigurazione di un account SMS: il numero deve essere correggibile.

Perché questo file esiste. Finché il passo di riconfigurazione toccava il solo PIN, chi
cambiava numero di telefono **non aveva nessuna via d'uscita**: la riautenticazione continuava
a spedire l'SMS al vecchio numero, e l'unico rimedio era eliminare e riaggiungere
l'integrazione, perdendo entity_id e storico di oltre cento entità. Lo stesso valeva per un
numero digitato male in fase di configurazione — ed è un caso tutt'altro che teorico, visto che
la normalizzazione del numero ha avuto per un po' un difetto che ne amputava alcune famiglie.

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
    """Trasforma l'entry di prova in un account SMS (registrato col numero, senza e-mail)."""
    hass.config_entries.async_update_entry(
        integrazione_avviata,
        data={**integrazione_avviata.data, CONF_EMAIL: "",
              CONF_PHONE: FX.PHONE, CONF_AREA_CODE: FX.AREA_CODE},
    )
    await hass.async_block_till_done()
    return integrazione_avviata


async def _apri(hass, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE,
                         "entry_id": entry.entry_id})


async def test_il_campo_numero_compare_solo_agli_account_sms(hass, entry_sms):
    campi = {str(k) for k in (await _apri(hass, entry_sms))["data_schema"].schema}
    assert CONF_PHONE in campi and CONF_AREA_CODE in campi


async def test_l_account_email_non_vede_il_campo_numero(hass, integrazione_avviata):
    """Offrire il campo a chi accede con l'e-mail lo inviterebbe a compilare qualcosa che non
    verrà mai usato."""
    campi = {str(k) for k in (await _apri(hass, integrazione_avviata))["data_schema"].schema}
    assert CONF_PHONE not in campi and CONF_AREA_CODE not in campi


async def test_il_numero_attuale_e_proposto_come_valore_di_partenza(hass, entry_sms):
    """A differenza del PIN, che è una credenziale e si riscrive da zero: chi entra qui per
    cambiare una cifra deve vedere da dove parte."""
    schema = (await _apri(hass, entry_sms))["data_schema"].schema
    campo = next(k for k in schema if str(k) == CONF_PHONE)
    assert campo.default() == FX.PHONE


async def test_cambiare_numero_lo_scrive_nell_entry(hass, entry_sms):
    nuovo = "3009876543"                                  # PHONE_PLACEHOLDER
    result = await _apri(hass, entry_sms)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PHONE: nuovo, CONF_AREA_CODE: FX.AREA_CODE, CONF_PIN: FX.PIN})
    await hass.async_block_till_done()

    assert entry_sms.data[CONF_PHONE] == nuovo
    assert entry_sms.data[CONF_AREA_CODE] == FX.AREA_CODE


async def test_il_numero_passa_dalla_stessa_normalizzazione_del_primo_accesso(hass, entry_sms):
    """Non una seconda copia della pulizia: la stessa. Due copie divergono."""
    result = await _apri(hass, entry_sms)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PHONE: "+39 300 987.65-43", CONF_AREA_CODE: "+39",  # PHONE_PLACEHOLDER
         CONF_PIN: FX.PIN})
    await hass.async_block_till_done()

    assert entry_sms.data[CONF_PHONE] == "3009876543"      # PHONE_PLACEHOLDER
    assert entry_sms.data[CONF_AREA_CODE] == "39"


async def test_un_numero_impossibile_viene_rifiutato(hass, entry_sms):
    """Meglio un errore nel form che un SMS spedito nel vuoto — o, peggio, al telefono di un
    estraneo."""
    prima = entry_sms.data[CONF_PHONE]
    result = await _apri(hass, entry_sms)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "12", CONF_AREA_CODE: "39", CONF_PIN: FX.PIN})

    assert result["errors"]["base"] == "phone_invalid"
    assert entry_sms.data[CONF_PHONE] == prima, "l'entry non va toccato se il dato è rifiutato"


async def test_dopo_un_rifiuto_il_pin_non_torna_a_schermo(hass, entry_sms):
    """Il numero sì (è comodo e non è un segreto), il PIN mai: è una credenziale, e questa
    schermata finisce negli screenshot allegati alle richieste di aiuto."""
    result = await _apri(hass, entry_sms)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "12", CONF_AREA_CODE: "39", CONF_PIN: FX.PIN})

    schema = result["data_schema"].schema
    campo_pin = next(k for k in schema if str(k) == CONF_PIN)
    import voluptuous as vol
    assert getattr(campo_pin, "description", None) in (None, {}) or \
        FX.PIN not in str(getattr(campo_pin, "description", ""))
    assert getattr(campo_pin, "default", vol.UNDEFINED) in (None, vol.UNDEFINED)
