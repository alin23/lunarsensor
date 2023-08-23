from __future__ import annotations

import json
import logging
import os
import time

import aiohttp
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

app = FastAPI()
logging.basicConfig()
_LOGGER = logging.getLogger(__name__)
_LOGGER.level = logging.DEBUG if os.getenv("SENSOR_DEBUG") == "1" else logging.INFO

POLLING_SECONDS = 2
CLIENT: aiohttp.ClientSession | None = None
last_lux = 400


@app.on_event("startup")
async def startup_event():
    global CLIENT

    CLIENT = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
    await CLIENT.__aenter__()


@app.on_event("shutdown")
async def shutdown() -> None:
    await CLIENT.__aexit__(None, None, None)


async def make_lux_response():
    global last_lux
    lux = None
    try:
        lux = await read_lux()
    except Exception as exc:
        _LOGGER.exception(exc)
    if lux is not None and lux != last_lux:
        _LOGGER.debug(f"Sending {lux} lux")
        last_lux = lux

    return {"id": "sensor-ambient_light", "state": f"{last_lux} lx", "value": last_lux}


async def sensor_reader(request):
    while not await request.is_disconnected():
        yield {"event": "state", "data": json.dumps(await make_lux_response())}

        time.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light")
async def sensor():
    return await make_lux_response()


@app.get("/events")
async def events(request: Request):
    event_generator = sensor_reader(request)
    return EventSourceResponse(event_generator)


HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL", "http://supervisor/core")
SENSOR_ENTITY_ID = os.getenv("SENSOR_ENTITY_ID")
_LOGGER.info(f"Using lux sensor {SENSOR_ENTITY_ID}")


async def read_lux():
    if not CLIENT:
        raise Exception("Client not defined")
    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    async with CLIENT.get(
            f"{HOME_ASSISTANT_URL}/api/states/{SENSOR_ENTITY_ID}",
            headers={"Authorization": f"Bearer {supervisor_token}"}
    ) as response:
        _sensor = await response.json()
        if not _sensor or not _sensor.get("state"):
            _LOGGER.warning(f"No state found in response: {_sensor}")
            return None
        return float(_sensor["state"])
