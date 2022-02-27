"""Support for the Netatmo cameras."""
from __future__ import annotations

import logging
from typing import Any, cast

import aiohttp
from pyatmo import ApiError as NetatmoApiError, modules as NaModules
from pyatmo.modules.device_types import (
    DEVICE_DESCRIPTION_MAP,
    DeviceCategory as NetatmoDeviceCategory,
    DeviceType as NetatmoDeviceType,
)
import voluptuous as vol

from homeassistant.components.camera import SUPPORT_STREAM, Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CAMERA_LIGHT_MODE,
    ATTR_PERSON,
    ATTR_PERSONS,
    CAMERA_LIGHT_MODES,
    CONF_URL_SECURITY,
    DATA_CAMERAS,
    DATA_EVENTS,
    DATA_HANDLER,
    DATA_PERSONS,
    DOMAIN,
    EVENT_TYPE_LIGHT_MODE,
    EVENT_TYPE_OFF,
    EVENT_TYPE_ON,
    MANUFACTURER,
    SERVICE_SET_CAMERA_LIGHT,
    SERVICE_SET_PERSON_AWAY,
    SERVICE_SET_PERSONS_HOME,
    WEBHOOK_LIGHT_MODE,
    WEBHOOK_NACAMERA_CONNECTION,
    WEBHOOK_PUSH_TYPE,
)
from .data_handler import EVENT, HOME, SIGNAL_NAME, NetatmoDataHandler
from .netatmo_entity_base import NetatmoBase

_LOGGER = logging.getLogger(__name__)

DEFAULT_QUALITY = "high"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Netatmo camera platform."""
    data_handler = hass.data[DOMAIN][entry.entry_id][DATA_HANDLER]

    account_topology = data_handler.account

    if not account_topology or not account_topology.raw_data:
        raise PlatformNotReady

    entities = []
    for home_id in account_topology.homes:
        await data_handler.subscribe(HOME, f"{HOME}-{home_id}", None, home_id=home_id)
        await data_handler.subscribe(EVENT, f"{EVENT}-{home_id}", None, home_id=home_id)

        for camera in account_topology.homes[home_id].modules.values():
            if camera.device_category is NetatmoDeviceCategory.camera:
                entities.append(NetatmoCamera(data_handler, camera))

    for home in account_topology.homes.values():
        if home.entity_id is None:
            continue

        hass.data[DOMAIN][DATA_PERSONS][home.entity_id] = {
            person.entity_id: person.pseudo for person in home.persons.values()
        }

    _LOGGER.debug("Adding cameras %s", entities)
    async_add_entities(entities, True)

    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_SET_PERSONS_HOME,
        {vol.Required(ATTR_PERSONS): vol.All(cv.ensure_list, [cv.string])},
        "_service_set_persons_home",
    )
    platform.async_register_entity_service(
        SERVICE_SET_PERSON_AWAY,
        {vol.Optional(ATTR_PERSON): cv.string},
        "_service_set_person_away",
    )
    platform.async_register_entity_service(
        SERVICE_SET_CAMERA_LIGHT,
        {vol.Required(ATTR_CAMERA_LIGHT_MODE): vol.In(CAMERA_LIGHT_MODES)},
        "_service_set_camera_light",
    )


class NetatmoCamera(NetatmoBase, Camera):
    """Representation of a Netatmo camera."""

    def __init__(
        self,
        data_handler: NetatmoDataHandler,
        camera: NaModules.NOC | NaModules.NACamera | NaModules.NDB,
    ) -> None:
        """Set up for access to the Netatmo camera images."""
        Camera.__init__(self)
        super().__init__(data_handler)

        self._camera = camera
        self._id = self._camera.entity_id
        self._home_id = self._camera.home.entity_id
        self._device_name = self._camera.name
        self._attr_name = f"{MANUFACTURER} {self._device_name}"
        self._model = self._camera.device_type
        self._netatmo_type = CONF_URL_SECURITY
        self._attr_unique_id = f"{self._id}-{self._model}"
        self._quality = DEFAULT_QUALITY
        self._vpnurl: str | None = None
        self._localurl: str | None = None
        self._monitoring: bool | None = None
        self._sd_status: int | None = None
        self._alim_status: int | None = None
        self._is_local: bool | None = None
        self._light_state = None
        self._attr_brand = MANUFACTURER

        self._signal_name = f"{HOME}-{self._home_id}"
        self._publishers.extend(
            [
                {
                    "name": HOME,
                    "home_id": self._home_id,
                    SIGNAL_NAME: self._signal_name,
                },
                {
                    "name": EVENT,
                    "home_id": self._home_id,
                    SIGNAL_NAME: self._signal_name,
                },
            ]
        )

    async def async_added_to_hass(self) -> None:
        """Entity created."""
        await super().async_added_to_hass()

        for event_type in (EVENT_TYPE_LIGHT_MODE, EVENT_TYPE_OFF, EVENT_TYPE_ON):
            self.data_handler.config_entry.async_on_unload(
                async_dispatcher_connect(
                    self.hass,
                    f"signal-{DOMAIN}-webhook-{event_type}",
                    self.handle_event,
                )
            )

        self.hass.data[DOMAIN][DATA_CAMERAS][self._id] = self._device_name

    @callback
    def handle_event(self, event: dict) -> None:
        """Handle webhook events."""
        data = event["data"]

        if not data.get("camera_id"):
            return

        if data["home_id"] == self._home_id and data["camera_id"] == self._id:
            if data[WEBHOOK_PUSH_TYPE] in ("NACamera-off", "NACamera-disconnection"):
                self._attr_is_streaming = False
                self._monitoring = False
            elif data[WEBHOOK_PUSH_TYPE] in (
                "NACamera-on",
                WEBHOOK_NACAMERA_CONNECTION,
            ):
                self._attr_is_streaming = True
                self._monitoring = True
            elif data[WEBHOOK_PUSH_TYPE] == WEBHOOK_LIGHT_MODE:
                self._light_state = data["sub_type"]
                self._attr_extra_state_attributes.update(
                    {"light_state": self._light_state}
                )

            self.async_write_ha_state()
            return

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        try:
            return cast(bytes, await self._camera.async_get_live_snapshot())
        except (
            aiohttp.ClientPayloadError,
            aiohttp.ContentTypeError,
            aiohttp.ServerDisconnectedError,
            aiohttp.ClientConnectorError,
            NetatmoApiError,
        ) as err:
            _LOGGER.debug("Could not fetch live camera image (%s)", err)
        return None

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return SUPPORT_STREAM

    async def async_turn_off(self) -> None:
        """Turn off camera."""
        await self._camera.async_monitoring_off()

    async def async_turn_on(self) -> None:
        """Turn on camera."""
        await self._camera.async_monitoring_on()

    async def stream_source(self) -> str:
        """Return the stream source."""
        if self._camera.is_local:
            await self._camera.async_update_camera_urls()

        url = "{0}/live/files/{1}/index.m3u8"
        if self._camera.local_url:
            return url.format(self._camera.local_url, self._quality)
        return url.format(self._camera.vpn_url, self._quality)

    @property
    def model(self) -> str:
        """Return the camera model."""
        return DEVICE_DESCRIPTION_MAP[getattr(NetatmoDeviceType, self._model)]

    @callback
    def async_update_callback(self) -> None:
        """Update the entity's state."""
        self._vpnurl = self._camera.vpn_url
        self._localurl = self._camera.local_url
        self._sd_status = self._camera.sd_status
        self._alim_status = self._camera.alim_status
        self._is_local = self._camera.is_local
        self._attr_is_on = self._alim_status is not None
        self._attr_available = self._alim_status is not None

        if self._camera.monitoring is not None:
            self._attr_is_streaming = self._camera.monitoring
            self._attr_motion_detection_enabled = self._camera.monitoring

        self.hass.data[DOMAIN][DATA_EVENTS][self._id] = self.process_events(
            self._camera.events
        )

        self._attr_extra_state_attributes.update(
            {
                "id": self._id,
                "monitoring": self._monitoring,
                "sd_status": self._sd_status,
                "alim_status": self._alim_status,
                "is_local": self._is_local,
                "vpn_url": self._vpnurl,
                "local_url": self._localurl,
                "light_state": self._light_state,
            }
        )

    def process_events(self, event_list: list) -> dict:
        """Add meta data to events."""
        events = {}
        for event in event_list:
            if not (video_id := getattr(event, "video_id")):
                continue
            event_data = event.__dict__
            if "subevents" in event_data:
                event_data["subevents"] = [
                    event.__dict__ for event in event_data["subevents"]
                ]
            event_data["media_url"] = self.get_video_url(video_id)
            events[event.event_time] = event_data
        return events

    def get_video_url(self, video_id: str) -> str:
        """Get video url."""
        if self._is_local:
            return f"{self._localurl}/vod/{video_id}/files/{self._quality}/index.m3u8"
        return f"{self._vpnurl}/vod/{video_id}/files/{self._quality}/index.m3u8"

    def fetch_person_ids(self, persons: list[str | None]) -> list[str]:
        """Fetch matching person ids for give list of persons."""
        person_ids = []
        person_id_errors = []

        for person in persons:
            person_id = None
            for pid, data in self._camera.home.persons.items():
                if data.pseudo == person:
                    person_ids.append(pid)
                    person_id = pid
                    break

            if person_id is None:
                person_id_errors.append(person)

        if person_id_errors:
            raise HomeAssistantError(f"Person(s) not registered {person_id_errors}")

        return person_ids

    async def _service_set_persons_home(self, **kwargs: Any) -> None:
        """Service to change current home schedule."""
        persons = kwargs.get(ATTR_PERSONS, [])
        person_ids = self.fetch_person_ids(persons)

        await self._camera.home.async_set_persons_home(person_ids=person_ids)
        _LOGGER.debug("Set %s as at home", persons)

    async def _service_set_person_away(self, **kwargs: Any) -> None:
        """Service to mark a person as away or set the home as empty."""
        person = kwargs.get(ATTR_PERSON)
        person_ids = self.fetch_person_ids([person] if person else [])
        person_id = next(iter(person_ids), None)

        await self._camera.home.async_set_persons_away(
            person_id=person_id,
        )

        if person_id:
            _LOGGER.debug("Set %s as away %s", person, person_id)
        else:
            _LOGGER.debug("Set home as empty")

    async def _service_set_camera_light(self, **kwargs: Any) -> None:
        """Service to set light mode."""
        if not isinstance(self._camera, NaModules.netatmo.NOC):
            raise HomeAssistantError(f"{self._model} does not have a floodlight")
        mode = str(kwargs.get(ATTR_CAMERA_LIGHT_MODE))
        _LOGGER.debug("Turn %s camera light for '%s'", mode, self._attr_name)
        await self._camera.async_set_floodlight_state(mode)
