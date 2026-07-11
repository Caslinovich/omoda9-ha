"""Base entity Omoda 9: aggancio al coordinator + device_info comune.

Continuità entity_id (FASE 3d): per non perdere storico recorder/dashboard al
cutover dal bridge, ogni entità FORZA il proprio `entity_id` invece di lasciarlo
derivare implicitamente. L'object_id di default = slugify(nome) — che riproduce
ESATTAMENTE gli id `omoda9_*` già generati dal bridge (has_entity_name=False →
HA slugifica il solo nome). Dove il bridge usa un id non derivabile dal nome
(es. i pulsanti comando = `omoda9_<key>`) si passa `object_id` esplicito.
"""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DEFAULT_VEHICLE_NAME, DOMAIN
from .coordinator import Omoda9Coordinator


def field_on(v) -> bool | None:
    """Interpreta un campo 5A02 come acceso/aperto (True), spento/chiuso (False)
    o ASSENTE (None).

    `None` / `"None"` / `""` = campo assente → ritorna `None`, così a livello entità
    emerge il valore ripristinato (o `unknown`) invece di un falso `False`. Altrimenti
    vero se diverso da zero, con confronto NUMERICO quando possibile (`"0.0"` = spento,
    allineato fra binary_sensor/lock/switch/cover); fallback testuale per i booleani."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "None"):
        return None
    try:
        return float(s) != 0.0
    except (TypeError, ValueError):
        return s.lower() not in ("false", "off", "no")


class Omoda9Entity(CoordinatorEntity[Omoda9Coordinator]):
    """Entità base: device unico 'Omoda 9' identificato dal VIN."""

    # has_entity_name=True + translation_key → il NOME dell'entità è TRADOTTO (it/en) e HA lo
    # antepone al device → "Omoda 9 Battery" / "Jaecoo 7 Battery". L'entity_id resta lo stile
    # bridge "omoda9_*" (impostato esplicito sotto, da `name`/`object_id`) → storico intatto.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Omoda9Coordinator,
        name: str,
        unique_suffix: str,
        *,
        object_id: str | None = None,
        entity_id_format: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        # `name` NON è più il friendly name (lo dà translation_key): lo teniamo solo per
        # calcolare l'object_id dell'entity_id e per i log. NON impostare _attr_name, altrimenti
        # vincerebbe sul translation_key.
        self._raw_name = name
        self._attr_unique_id = f"{coordinator.vin}_{unique_suffix}"
        oid = object_id or slugify(name)          # es. "omoda9_batteria"
        # translation_key = object_id senza il prefisso dominio → chiave in translations/*.json
        self._attr_translation_key = oid[len(DOMAIN) + 1:] if oid.startswith(f"{DOMAIN}_") else oid
        # entity_id ESPLICITO = continuità col bridge (default = slugify(name)).
        if entity_id_format:
            self.entity_id = entity_id_format.format(oid)
        # device dinamico: il nome riflette il veicolo reale (Omoda 9, Jaecoo 7…), letto
        # dal coordinator (nickname/modello da queryList, o override manuale). Il device è
        # identificato dal VIN → rinominarlo NON tocca entity_id né storico.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            name=coordinator.vehicle_name or DEFAULT_VEHICLE_NAME,
            manufacturer=coordinator.vehicle_brand or "Omoda",
            model=coordinator.vehicle_model or None,
        )


class Omoda9OptimisticMixin:
    """Stato ottimistico per gli attuatori (lock/switch/cover).

    Un comando ATTUA subito sull'auto, ma lo stato reale torna SOLO via MQTT a
    auto sveglia: l'ultimo valore "live" può restare fermo per ore. Dopo un'azione
    mostriamo immediatamente lo stato target (ottimistico) e lo teniamo finché non
    arriva un NUOVO messaggio dall'auto (avanza `last_seen`), che diventa la verità.
    Da usare come PRIMA classe base (precede Omoda9Entity nell'MRO)."""

    _opt_value = None
    _opt_anchor = None

    def _set_optimistic(self, value) -> None:
        self._opt_value = value
        self._opt_anchor = self.coordinator.data.get("last_seen")
        self.async_write_ha_state()

    def _clear_optimistic(self) -> None:
        self._opt_value = None
        self._opt_anchor = None

    async def _run_command(self, key: str, target, params: dict | None = None) -> None:
        """Attua un comando mostrando subito lo stato target (ottimistico).

        `params` = override parametrico del body (clima: temperatura/durata; ricarica
        programmata: piano). Su eccezione del comando (rete/auth/backend) ANNULLA
        l'ottimismo — così la card torna allo stato reale invece di restare bloccata
        su un target mai attuato — e propaga un errore leggibile (toast in UI).

        [coda] L'auto esegue UN comando alla volta: un secondo comando (o un doppio-tap) non
        viene rifiutato ma ASPETTA il suo turno nella coda del coordinator, che lo invia appena
        l'auto ha confermato il precedente."""
        self._set_optimistic(target)
        try:
            await self.coordinator.async_send_command(key, params)
        except Exception as err:  # noqa: BLE001 — qualunque fallimento del comando
            self._clear_optimistic()
            self.async_write_ha_state()
            raise HomeAssistantError(f"Comando «{key}» non riuscito: {err}") from err

    def _handle_coordinator_update(self) -> None:
        # un nuovo messaggio dall'auto (last_seen cambiato) invalida l'ottimismo
        if self._opt_value is not None and \
                self.coordinator.data.get("last_seen") != self._opt_anchor:
            self._clear_optimistic()
        super()._handle_coordinator_update()
