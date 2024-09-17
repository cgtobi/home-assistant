"""Support for Netatmo/BTicino/Legrande switches."""

from __future__ import annotations

import logging
from typing import Any

from pyatmo import modules as NaModules

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_URL_CONTROL, NETATMO_CREATE_SWITCH
from .data_handler import HOME, SIGNAL_NAME, NetatmoDevice
from .entity import NetatmoModuleEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Netatmo switch platform."""

    @callback
    def _create_entity(netatmo_device: NetatmoDevice) -> None:
        entity = NetatmoSwitch(netatmo_device)
        _LOGGER.debug("Adding switch %s", entity)
        async_add_entities([entity])

    entry.async_on_unload(
        async_dispatcher_connect(hass, NETATMO_CREATE_SWITCH, _create_entity)
    )


class NetatmoSwitch(NetatmoModuleEntity, SwitchEntity):
    """Representation of a Netatmo switch device."""

    _attr_name = None
    _attr_configuration_url = CONF_URL_CONTROL
    device: NaModules.Switch

    def __init__(
        self,
        netatmo_device: NetatmoDevice,
    ) -> None:
        """Initialize the Netatmo device."""
        super().__init__(netatmo_device)
        self._signal_name = f"{HOME}-{self.home.entity_id}"
        self._publishers.extend(
            [
                {
                    "name": HOME,
                    "home_id": self.home.entity_id,
                    SIGNAL_NAME: self._signal_name,
                },
            ]
        )
        self._attr_unique_id = f"{self.device.entity_id}-{self.device_type}"
        self._attr_is_on = self.device.on

    @callback
    def async_update_callback(self) -> None:
        """Update the entity's state."""
        self._attr_is_on = self.device.on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the zone on."""
        await self.device.async_on()
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the zone off."""
        await self.device.async_off()
        self._attr_is_on = False
        self.async_write_ha_state()


# class NetatmoClimateModeSwitch(NetatmoBaseEntity, SwitchEntity):
#     """Representation of a Netatmo switch device."""

#     _attr_name = None

#     def __init__(self, netatmo_home: NetatmoHome) -> None:
#         """Initialize the switch entity."""
#         super().__init__(netatmo_home.data_handler)

#         self.home = netatmo_home.home

#         self._publishers.extend(
#             [
#                 {
#                     "name": HOME,
#                     "home_id": self.home.entity_id,
#                     SIGNAL_NAME: netatmo_home.signal_name,
#                 },
#             ]
#         )
#         self._attr_device_info = DeviceInfo(
#             identifiers={(DOMAIN, self.home.entity_id)},
#             name=self.home.name,
#             manufacturer=MANUFACTURER,
#             model="Climate",
#             configuration_url=CONF_URL_ENERGY,
#         )

#         self._attr_unique_id = f"{self.home.entity_id}-schedule-select"


#     async def async_added_to_hass(self) -> None:
#         """Entity created."""
#         await super().async_added_to_hass()

#         self.async_on_remove(
#             async_dispatcher_connect(
#                 self.hass,
#                 f"signal-{DOMAIN}-webhook-{EVENT_TYPE_SCHEDULE}",
#                 self.handle_event,
#             )
#         )

#     @callback
#     def async_update_callback(self) -> None:
#         """Update the entity's state."""
#         self._attr_current_option = self.get_selected_schedule()
#         self._attr_options = self.get_available_schedules()
#         self.hass.data[DOMAIN][DATA_SCHEDULES][self.home.entity_id] = (
#             self.home.schedules
#         )
