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
import time

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
# None, never a number. This used to be seeded to 400.0 and returned on every failure path,
# so a sensor that was misconfigured, unwired or throwing served a plausible office reading
# forever — and nothing downstream could tell it from a real one. Lunar would adapt
# confidently to a constant. No reading now means no reading: the endpoints answer 503 and
# the event stream stays quiet.
last_lux = None
# Monotonic timestamp of the last REAL reading, so a stale one can be retired.
last_lux_at = None
last_cct = None

# How long a reading stays servable after the sensor stops producing new ones. Long enough
# to ride out a transient blip at POLLING_SECONDS cadence (a sensor that read 300 lux two
# seconds ago is still about 300 lux), short enough that a dead sensor stops pinning
# brightness to a value that is no longer true.
MAX_READING_AGE_SECONDS = 30
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


async def current_lux():
    """The last trustworthy reading, or None when there is nothing honest to serve.

    Never invents a value: a fabricated lux figure is indistinguishable from a real one
    downstream, and Lunar will happily adapt to it.
    """
    global last_lux, last_lux_at
    try:
        lux = await read_lux()
    except Exception as exc:
        log.exception(exc)
        lux = None

    if lux is not None:
        if lux != last_lux:
            log.debug(f"Sending {lux} lux")
        last_lux = lux
        last_lux_at = time.monotonic()
        return lux

    if last_lux is None:
        return None

    if time.monotonic() - last_lux_at > MAX_READING_AGE_SECONDS:
        log.warning(
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
        # Nothing is emitted while the sensor has no reading. Lunar treats silence as
        # "no new data" and keeps its last value, which is the honest outcome; a synthesized
        # event would instead be adapted to as though the room had actually changed.
        lux = await make_lux_response()
        if lux is not None:
            yield {"event": "state", "data": json.dumps(lux)}
        if supports_color:
            cct = await make_cct_response()
            if cct is not None:
                yield {"event": "state", "data": json.dumps(cct)}

        await asyncio.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light")
async def sensor():
    response = await make_lux_response()
    if response is None:
        # 503 rather than a made-up number. Lunar only adopts a responder that returns a
        # decodable body with a `value`, so this reads as "sensor present but not ready"
        # and no brightness decision is made on it.
        return JSONResponse(
            {"error": "no ambient light reading available"}, status_code=503
        )
    return response


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
    """Blocking part of the reading. Runs in a worker thread, so it's safe to do real I/O here.

    Return None when the sensor cannot be read. Do NOT return a placeholder number: the
    server cannot tell it apart from a real measurement and Lunar will adapt to it.
    """
    if os.path.exists("/tmp/lux"):
        with open("/tmp/lux") as f:
            raw = f.read().strip()
        return float(raw) if raw else None

    return None


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
