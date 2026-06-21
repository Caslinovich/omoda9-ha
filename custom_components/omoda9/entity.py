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

from .const import DOMAIN
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

    # has_entity_name=False + nomi espliciti "Omoda9 …" → entity_id stile bridge.
    _attr_has_entity_name = False

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
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.vin}_{unique_suffix}"
        # entity_id ESPLICITO = continuità col bridge (default = slugify(name)).
        if entity_id_format:
            self.entity_id = entity_id_format.format(object_id or slugify(name))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            name="Omoda 9",
            manufacturer="Omoda",
            model="Omoda 9",
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
        su un target mai attuato — e propaga un errore leggibile (toast in UI)."""
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
