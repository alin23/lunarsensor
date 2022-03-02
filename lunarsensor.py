import os
import time
import json

import uvicorn
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

app = FastAPI()

POLLING_SECONDS = 2


async def make_lux_response():
    lux = await read_lux()
    return {"id": "sensor-ambient_light_tsl2561", "state": f"{lux} lx", "value": lux}


async def sensor_reader(request):
    while not await request.is_disconnected():
        yield {"event": "state", "data": json.dumps(await make_lux_response())}

        time.sleep(POLLING_SECONDS)


@app.get("/sensor/ambient_light_tsl2561")
async def sensor(request: Request):
    return await make_lux_response()


@app.get("/events")
async def events(request: Request):
    event_generator = sensor_reader(request)
    return EventSourceResponse(event_generator)


# Do the sensor reading logic below


async def read_lux():
    return 400.00
