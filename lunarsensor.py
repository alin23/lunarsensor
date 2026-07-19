"""Custom Ambient Light Sensor server for the Lunar macOS app.

Serves the same HTTP API as the ESPHome sensor firmware (one-shot reads plus a
Server-Sent-Events stream) and announces itself over mDNS as `_lunarsensor._tcp`,
so Lunar discovers it the moment it starts.

Implement your sensor logic in `read_lux()` at the bottom of this file. If your
sensor also measures ambient color, implement `read_color_temperature()` too: Lunar
uses it to drive True Tone for external monitors.
"""

import asyncio
import contextlib
import json
import logging
import os
import socket
import sys

import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

logging.basicConfig()
log = logging.getLogger("lunarsensor")
log.level = logging.DEBUG if os.getenv("SENSOR_DEBUG") == "1" else logging.INFO


POLLING_SECONDS = 2
# "::" is dual-stack on Linux but IPv6-only on macOS, where the mDNS A record would
# then point clients at an address nobody listens on.
HOST = os.getenv("HOST", "0.0.0.0" if sys.platform == "darwin" else "::")
PORT = int(os.getenv("PORT", "80"))

CLIENT = None
ZEROCONF = None
last_lux = 400.0
last_cct = None
supports_color = False
# Sensor reads are usually blocking (a file, a serial port, an I2C bus) and several clients
# can be streaming at once. Serialize them so two readers can't interleave on the same device.
sensor_lock = asyncio.Lock()


def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


async def register_mdns():
    """Announce `_lunarsensor._tcp` so Lunar finds the server without polling.

    Disable with SENSOR_MDNS=0 (e.g. when another instance on the host already
    advertises)."""
    global ZEROCONF
    if os.getenv("SENSOR_MDNS") == "0":
        return

    hostname = socket.gethostname().split(".")[0]
    info = ServiceInfo(
        "_lunarsensor._tcp.local.",
        f"{hostname}._lunarsensor._tcp.local.",
        addresses=[socket.inet_aton(local_ip())],
        port=PORT,
        properties={"color": "1" if supports_color else "0", "source": "lunarsensor.py"},
        server=f"{hostname}.local.",
    )
    try:
        ZEROCONF = AsyncZeroconf()
        await ZEROCONF.async_register_service(info)
        log.info(f"Advertising _lunarsensor._tcp on port {PORT}")
    except OSError as exc:
        log.warning(f"mDNS advertising unavailable: {exc}")
        ZEROCONF = None


@contextlib.asynccontextmanager
async def lifespan(app):
    global CLIENT, supports_color

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client:
        CLIENT = client

        # A working color reading at startup enables the color endpoints and the
        # `color=1` mDNS flag.
        try:
            supports_color = await read_color_temperature() is not None
        except Exception:
            supports_color = False

        await register_mdns()
        yield
        if ZEROCONF is not None:
            await ZEROCONF.async_close()


app = FastAPI(lifespan=lifespan)


async def make_lux_response():
    global last_lux
    try:
        lux = await read_lux()
    except Exception as exc:
        log.exception(exc)
    else:
        if lux is not None and lux != last_lux:
            log.debug(f"Sending {lux} lux")
            last_lux = lux

    return {"id": "sensor-ambient_light", "state": f"{last_lux} lx", "value": last_lux}


async def make_cct_response():
    global last_cct
    try:
        cct = await read_color_temperature()
    except Exception as exc:
        log.exception(exc)
    else:
        if cct is not None and cct != last_cct:
            log.debug(f"Sending {cct}K color temperature")
            last_cct = cct

    if last_cct is None:
        return None
    return {
        "id": "sensor-ambient_color_temperature",
        "state": f"{last_cct} K",
        "value": last_cct,
    }


async def sensor_reader(request):
    while not await request.is_disconnected():
        yield {"event": "state", "data": json.dumps(await make_lux_response())}
        if supports_color:
            cct = await make_cct_response()
            if cct is not None:
                yield {"event": "state", "data": json.dumps(cct)}

        await asyncio.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light")
async def sensor():
    return await make_lux_response()


@app.get("/sensor/ambient_color_temperature")
async def color_sensor():
    response = await make_cct_response() if supports_color else None
    if response is None:
        return JSONResponse({"error": "no color sensor"}, status_code=404)
    return response


@app.get("/events")
async def events(request: Request):
    event_generator = sensor_reader(request)
    return EventSourceResponse(event_generator)


def main():
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning" if os.getenv("SENSOR_DEBUG") != "1" else "debug")


# Do the sensor reading logic below


def _sync_read_lux():
    """Blocking part of the reading. Runs in a worker thread, so it's safe to do real I/O here."""
    if os.path.exists("/tmp/lux"):
        with open("/tmp/lux") as f:
            return float(f.read().strip() or "400.0")

    return 400.00


async def read_lux():
    # Offloaded to the default executor and serialized with `sensor_lock`: doing blocking I/O
    # directly on the event loop stalls every connected client, including the SSE streams.
    loop = asyncio.get_running_loop()
    async with sensor_lock:
        return await loop.run_in_executor(None, _sync_read_lux)


async def read_color_temperature():
    """Ambient color temperature in Kelvin, or None when the sensor can't measure color.

    Implementing this (e.g. from a TCS34725) lets Lunar adapt the white point of
    external monitors to the room's light (True Tone). Example with /tmp/cct:

        def _sync_read_cct():
            if os.path.exists("/tmp/cct"):
                with open("/tmp/cct") as f:
                    return float(f.read().strip() or "6500")

        loop = asyncio.get_running_loop()
        async with sensor_lock:
            return await loop.run_in_executor(None, _sync_read_cct)

    Use the same executor + `sensor_lock` shape as `read_lux` above if the reading blocks.
    """
    return None


if __name__ == "__main__":
    main()
