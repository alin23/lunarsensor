"""Lunar Sensor Home Assistant addon.

Polls Home Assistant sensor entities for ambient light (and optionally ambient color
temperature) and serves them to the Lunar macOS app over the same HTTP API as the
ESPHome sensor firmware, announced over mDNS as `_lunarsensor._tcp`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket

import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

logging.basicConfig()
_LOGGER = logging.getLogger(__name__)
_LOGGER.level = logging.DEBUG if os.getenv("SENSOR_DEBUG") == "1" else logging.INFO

POLLING_SECONDS = 2
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8899"))

HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL", "http://supervisor/core")
# Both are optional. With no lux entity configured the add-on picks one itself at startup
# (see `discover_lux_entity`), so a fresh install needs no configuration at all.
SENSOR_ENTITY_ID = os.getenv("SENSOR_ENTITY_ID") or None
COLOR_ENTITY_ID = os.getenv("COLOR_ENTITY_ID") or None

CLIENT: aiohttp.ClientSession | None = None
ZEROCONF: AsyncZeroconf | None = None
last_lux = 400.0
last_cct: float | None = None


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


async def register_mdns() -> None:
    """Announce `_lunarsensor._tcp` so Lunar discovers the addon instantly.

    Needs `host_network: true` (multicast doesn't leave the container otherwise)."""
    global ZEROCONF
    if os.getenv("SENSOR_MDNS") == "0":
        return

    hostname = socket.gethostname().split(".")[0]
    info = ServiceInfo(
        "_lunarsensor._tcp.local.",
        f"{hostname}._lunarsensor._tcp.local.",
        addresses=[socket.inet_aton(local_ip())],
        port=PORT,
        properties={
            "color": "1" if COLOR_ENTITY_ID else "0",
            "source": "homeassistant-addon",
        },
        server=f"{hostname}.local.",
    )
    try:
        ZEROCONF = AsyncZeroconf()
        await ZEROCONF.async_register_service(info)
        _LOGGER.info(f"Advertising _lunarsensor._tcp on port {PORT}")
    except OSError as exc:
        _LOGGER.warning(f"mDNS advertising unavailable: {exc}")
        ZEROCONF = None


async def discover_lux_entity() -> str | None:
    """Find the ambient light entity when the user didn't name one.

    This is what lets the add-on be installed with a single click and no configuration: it asks
    Home Assistant for everything with `device_class: illuminance` and takes the only candidate.
    With more than one it refuses to guess, listing them so the user can set `sensor_entity_id`.
    """
    if not CLIENT:
        return None

    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    try:
        async with CLIENT.get(
            f"{HOME_ASSISTANT_URL}/api/states",
            headers={"Authorization": f"Bearer {supervisor_token}"},
        ) as response:
            states = await response.json()
    except Exception as exc:
        _LOGGER.warning(f"Could not list entities to find a light sensor: {exc}")
        return None

    candidates = []
    for state in states or []:
        attributes = state.get("attributes") or {}
        if attributes.get("device_class") != "illuminance":
            continue
        # An entity that isn't reporting a number right now can't drive brightness.
        try:
            float(state.get("state"))
        except (TypeError, ValueError):
            continue
        candidates.append(state["entity_id"])

    if not candidates:
        _LOGGER.error(
            "No entity with device_class 'illuminance' found in Home Assistant. "
            "Set sensor_entity_id in the add-on configuration if your sensor uses a different class."
        )
        return None
    if len(candidates) > 1:
        _LOGGER.error(
            f"Found several light sensors ({', '.join(sorted(candidates))}). "
            "Set sensor_entity_id in the add-on configuration to pick one."
        )
        return None

    _LOGGER.info(f"Using {candidates[0]} (the only illuminance sensor in Home Assistant)")
    return candidates[0]


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global CLIENT, SENSOR_ENTITY_ID

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client:
        CLIENT = client
        if not SENSOR_ENTITY_ID:
            SENSOR_ENTITY_ID = await discover_lux_entity()
        _LOGGER.info(
            f"Using lux sensor {SENSOR_ENTITY_ID or 'none'}, color sensor {COLOR_ENTITY_ID or 'none'}"
        )
        await register_mdns()
        yield
        if ZEROCONF is not None:
            await ZEROCONF.async_close()


app = FastAPI(lifespan=lifespan)


async def read_entity_state(entity_id: str) -> float | None:
    if not CLIENT:
        raise Exception("Client not defined")
    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    async with CLIENT.get(
        f"{HOME_ASSISTANT_URL}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    ) as response:
        _sensor = await response.json()
        if not _sensor or not _sensor.get("state"):
            _LOGGER.warning(f"No state found in response: {_sensor}")
            return None
        try:
            return float(_sensor["state"])
        except ValueError:
            _LOGGER.warning(f"Non-numeric state for {entity_id}: {_sensor['state']}")
            return None


async def read_lux() -> float | None:
    # Nothing configured and nothing auto-discovered: keep serving the last value rather than
    # throwing on every poll. The startup log says what to fix.
    if not SENSOR_ENTITY_ID:
        return None
    return await read_entity_state(SENSOR_ENTITY_ID)


async def read_color_temperature() -> float | None:
    if not COLOR_ENTITY_ID:
        return None
    return await read_entity_state(COLOR_ENTITY_ID)


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


async def make_cct_response():
    global last_cct
    cct = None
    try:
        cct = await read_color_temperature()
    except Exception as exc:
        _LOGGER.exception(exc)
    if cct is not None and cct != last_cct:
        _LOGGER.debug(f"Sending {cct}K color temperature")
        last_cct = cct

    if last_cct is None:
        return None
    return {
        "id": "sensor-ambient_color_temperature",
        "state": f"{last_cct} K",
        "value": last_cct,
    }


async def sensor_reader(request: Request):
    while not await request.is_disconnected():
        yield {"event": "state", "data": json.dumps(await make_lux_response())}
        if COLOR_ENTITY_ID:
            cct = await make_cct_response()
            if cct is not None:
                yield {"event": "state", "data": json.dumps(cct)}

        await asyncio.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light")
async def sensor():
    return await make_lux_response()


@app.get("/sensor/ambient_color_temperature")
async def color_sensor():
    response = await make_cct_response() if COLOR_ENTITY_ID else None
    if response is None:
        return JSONResponse({"error": "no color sensor"}, status_code=404)
    return response


@app.get("/events")
async def events(request: Request):
    return EventSourceResponse(sensor_reader(request))


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
