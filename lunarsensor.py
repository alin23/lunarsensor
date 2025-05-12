import json
import logging
import os
import time
import asyncio

import aiohttp
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

app = FastAPI()
logging.basicConfig()
log = logging.getLogger("lunarsensor")
log.level = logging.DEBUG if os.getenv("SENSOR_DEBUG") == "1" else logging.INFO

POLLING_SECONDS = 2
CLIENT = None
last_lux = 400
sensor_lock = asyncio.Lock()  # serialize sensor or file access

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
    try:
        lux = await read_lux()
    except Exception as exc:
        log.exception(exc)
    else:
        if lux is not None and lux != last_lux:
            log.debug(f"Sending {lux} lux")
            last_lux = lux

    return {"id": "sensor-ambient_light", "state": f"{last_lux} lx", "value": last_lux}

async def sensor_reader(request):
    while not await request.is_disconnected():
        yield {"event": "state", "data": json.dumps(await make_lux_response())}
        await asyncio.sleep(POLLING_SECONDS)

@app.get("/sensor/ambient_light")
async def sensor():
    return await make_lux_response()

@app.get("/events")
async def events(request: Request):
    event_generator = sensor_reader(request)
    return EventSourceResponse(event_generator)

# Synchronous helper for reading lux (e.g. from file or sensor)
def _sync_read_lux():
    if os.path.exists("/tmp/lux"):
        with open("/tmp/lux") as f:
            return float(f.read().strip() or "400.0")
    return 400.0

async def read_lux():
    # Offload potentially blocking I/O into executor, serializing with a lock
    loop = asyncio.get_running_loop()
    async with sensor_lock:
        lux = await loop.run_in_executor(None, _sync_read_lux)
    return lux
