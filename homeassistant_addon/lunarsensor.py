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
import time

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
# None, never a number. This used to be seeded to 400.0 and returned on every failure path,
# so an add-on with no illuminance entity found, or a rejected Supervisor token, served a
# plausible office reading forever — and nothing downstream could tell it from a real one.
# Lunar would adapt confidently to a constant. No reading now means no reading: the
# endpoints answer 503 and the event stream stays quiet.
last_lux: float | None = None
# Monotonic timestamp of the last REAL reading, so a stale one can be retired.
last_lux_at: float | None = None
last_cct: float | None = None

# How long a reading stays servable after Home Assistant stops producing new ones. Long
# enough to ride out a restart or a brief unavailability at POLLING_SECONDS cadence, short
# enough that a removed or broken entity stops pinning brightness to a value that is no
# longer true.
MAX_READING_AGE_SECONDS = 30


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
    """Current lux from Home Assistant, or None when it cannot be read.

    Retries discovery while no entity is known. Home Assistant starts its integrations
    concurrently with its add-ons, so a cold boot on a Pi routinely has the add-on querying
    /api/states before the illuminance sensor exists. Discovering only once at startup left
    the add-on permanently sensor-less until someone restarted it by hand.
    """
    global SENSOR_ENTITY_ID
    if not SENSOR_ENTITY_ID:
        SENSOR_ENTITY_ID = await discover_lux_entity()
        if not SENSOR_ENTITY_ID:
            return None
        _LOGGER.info(f"Discovered lux sensor {SENSOR_ENTITY_ID}")
    return await read_entity_state(SENSOR_ENTITY_ID)


async def read_color_temperature() -> float | None:
    if not COLOR_ENTITY_ID:
        return None
    return await read_entity_state(COLOR_ENTITY_ID)


async def current_lux() -> float | None:
    """The last trustworthy reading, or None when there is nothing honest to serve.

    Never invents a value: a fabricated lux figure is indistinguishable from a real one
    downstream, and Lunar will happily adapt to it.
    """
    global last_lux, last_lux_at
    try:
        lux = await read_lux()
    except Exception as exc:
        _LOGGER.exception(exc)
        lux = None

    if lux is not None:
        if lux != last_lux:
            _LOGGER.debug(f"Sending {lux} lux")
        last_lux = lux
        last_lux_at = time.monotonic()
        return lux

    if last_lux is None:
        return None

    if time.monotonic() - last_lux_at > MAX_READING_AGE_SECONDS:
        _LOGGER.warning(
            f"No reading for over {MAX_READING_AGE_SECONDS}s; reporting the sensor as "
            f"unavailable instead of continuing to serve {last_lux} lx"
        )
        last_lux = None
        last_lux_at = None
        return None

    # A recent real reading: still the best answer available during a blip.
    return last_lux


async def make_lux_response():
    lux = await current_lux()
    if lux is None:
        return None
    return {"id": "sensor-ambient_light", "state": f"{lux} lx", "value": lux}


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
        # Nothing is emitted while there is no reading. Lunar treats silence as "no new
        # data" and keeps its last value, which is the honest outcome; a synthesized event
        # would instead be adapted to as though the room had actually changed.
        lux = await make_lux_response()
        if lux is not None:
            yield {"event": "state", "data": json.dumps(lux)}
        if COLOR_ENTITY_ID:
            cct = await make_cct_response()
            if cct is not None:
                yield {"event": "state", "data": json.dumps(cct)}

        await asyncio.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light")
async def sensor():
    response = await make_lux_response()
    if response is None:
        # 503 rather than a made-up number. Lunar only adopts a responder that returns a
        # decodable body with a `value`, so this reads as "add-on present but not ready"
        # and no brightness decision is made on it.
        return JSONResponse(
            {"error": "no ambient light reading available"}, status_code=503
        )
    return response


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
