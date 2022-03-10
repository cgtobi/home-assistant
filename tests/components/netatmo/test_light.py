"""The tests for Netatmo light."""
from unittest.mock import AsyncMock, patch

from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.netatmo import DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, CONF_WEBHOOK_ID

from .common import FAKE_WEBHOOK_ACTIVATION, selected_platforms, simulate_webhook

from tests.test_util.aiohttp import AiohttpClientMockResponse


async def test_light_setup_and_services(hass, config_entry, netatmo_auth):
    """Test setup and services."""
    with selected_platforms(["light"]):
        await hass.config_entries.async_setup(config_entry.entry_id)

        await hass.async_block_till_done()

    webhook_id = config_entry.data[CONF_WEBHOOK_ID]

    # Fake webhook activation
    await simulate_webhook(hass, webhook_id, FAKE_WEBHOOK_ACTIVATION)
    await hass.async_block_till_done()

    light_entity = "light.netatmo_garden"
    assert hass.states.get(light_entity).state == "unavailable"

    # Trigger light mode change
    response = {
        "event_type": "light_mode",
        "device_id": "12:34:56:00:a5:a4",
        "camera_id": "12:34:56:00:a5:a4",
        "event_id": "601dce1560abca1ebad9b723",
        "push_type": "NOC-light_mode",
        "sub_type": "on",
    }
    await simulate_webhook(hass, webhook_id, response)

    assert hass.states.get(light_entity).state == "on"

    # Trigger light mode change with erroneous webhook data
    response = {
        "event_type": "light_mode",
        "device_id": "12:34:56:00:a5:a4",
    }
    await simulate_webhook(hass, webhook_id, response)

    assert hass.states.get(light_entity).state == "on"

    # Test turning light off
    with patch("pyatmo.home.Home.async_set_state") as mock_set_state:
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: light_entity},
            blocking=True,
        )
        await hass.async_block_till_done()
        mock_set_state.assert_called_once_with(
            {"modules": [{"id": "12:34:56:00:a5:a4", "floodlight": "auto"}]}
        )

    # Test turning light on
    with patch("pyatmo.home.Home.async_set_state") as mock_set_state:
        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: light_entity},
            blocking=True,
        )
        await hass.async_block_till_done()
        mock_set_state.assert_called_once_with(
            {"modules": [{"id": "12:34:56:00:a5:a4", "floodlight": "on"}]}
        )


async def test_setup_component_no_devices(hass, config_entry):
    """Test setup with no devices."""
    fake_post_hits = 0

    async def fake_post_request_no_data(*args, **kwargs):
        """Fake error during requesting backend data."""
        nonlocal fake_post_hits
        fake_post_hits += 1
        return AiohttpClientMockResponse(
            method="POST",
            url=kwargs["url"],
            json={},
        )

    with patch(
        "homeassistant.components.netatmo.api.AsyncConfigEntryNetatmoAuth"
    ) as mock_auth, patch(
        "homeassistant.components.netatmo.PLATFORMS", ["light"]
    ), patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_config_entry_implementation",
    ), patch(
        "homeassistant.components.netatmo.webhook_generate_url"
    ):
        mock_auth.return_value.async_post_request.side_effect = (
            fake_post_request_no_data
        )
        mock_auth.return_value.async_addwebhook.side_effect = AsyncMock()
        mock_auth.return_value.async_dropwebhook.side_effect = AsyncMock()

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Fake webhook activation
        await simulate_webhook(
            hass, config_entry.data[CONF_WEBHOOK_ID], FAKE_WEBHOOK_ACTIVATION
        )
        await hass.async_block_till_done()

        assert fake_post_hits == 3

        assert hass.config_entries.async_entries(DOMAIN)
        assert len(hass.states.async_all()) == 0
