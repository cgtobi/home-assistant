"""The tests for Netatmo webhook events."""
from homeassistant.components.netatmo.const import DATA_DEVICE_IDS, DATA_PERSONS
from homeassistant.components.netatmo.webhook import async_handle_webhook
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.aiohttp import MockRequest


async def test_webhook_error_in_data(hass):
    """Test that errors in webhook data are handled."""
    webhook_called = False

    async def handle_event(_):
        nonlocal webhook_called
        webhook_called = True

    response = b'""webhook_activation"}'
    request = MockRequest(content=response, mock_source="test")

    async_dispatcher_connect(
        hass,
        "signal-netatmo-webhook-None",
        handle_event,
    )

    await async_handle_webhook(hass, "webhook_id", request)
    await hass.async_block_till_done()

    assert not webhook_called


async def test_webhook_person_event(hass):
    """Test that person events are handled."""
    webhook_called = False

    async def handle_event(_):
        nonlocal webhook_called
        webhook_called = True

    response = (
        b'{"user_id": "5c81004xxxxxxxxxx45f4",'
        b'"persons": [{"id": "e2bf7xxxxxxxxxxxxea3", "face_id": "5d66xxxxxx9b9",'
        b'"face_key": "89dxxxxx22", "is_known": true,'
        b'"face_url": "https://netatmocameraimage.blob.core.windows.net/production/5xxx"}],'
        b'"snapshot_id": "5d19bae867368a59e81cca89", "snapshot_key": "d3b3ae0229f7xb74cf8",'
        b'"snapshot_url": "https://netatmocameraimage.blob.core.windows.net/production/5xxxx",'
        b'"event_type": "person", "camera_id": "70:xxxxxx:a7", "device_id": "70:xxxxxx:a7",'
        b'"home_id": "5c5dxxxxxxxd594", "home_name": "Boulogne Billan.",'
        b'"event_id": "5d19bxxxxxxxxcca88",'
        b'"message": "Boulogne Billan.: Benoit has been seen by Indoor Camera ",'
        b'"push_type": "NACamera-person"}'
    )
    request = MockRequest(content=response, mock_source="test")

    hass.data["netatmo"] = {
        DATA_DEVICE_IDS: {},
        DATA_PERSONS: {},
    }

    async_dispatcher_connect(
        hass,
        "signal-netatmo-webhook-person",
        handle_event,
    )

    await async_handle_webhook(hass, "webhook_id", request)
    await hass.async_block_till_done()

    assert webhook_called
