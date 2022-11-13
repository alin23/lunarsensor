import json
import logging
import time

import aiohttp
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

app = FastAPI()
logging.basicConfig()

POLLING_SECONDS = 2
CLIENT = None
last_lux = 400


@app.on_event("startup")
async def startup_event():
    global CLIENT

    CLIENT = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
    await CLIENT.__aenter__()


async def make_lux_response():
    global last_lux
    try:
        lux = await read_lux()
    except Exception as exc:
        logging.exception(exc)
    else:
        if lux:
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


# Do the sensor reading logic below


async def read_lux():
    return 400.00
