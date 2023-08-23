<p align="center">
    <a href="https://lunar.fyi/"><img width="128" height="128" src="https://static.lunar.fyi/svg/lunar.svg"></a>
  <h1 align="center"><code>Lunar Sensor</code></h1>
  <h4 align="center">Create a custom Ambient Light Sensor on any device</h4>
</p>

---

This is a server that implements a custom Ambient Light Sensor for adapting monitor brightness with the [Lunar macOS app](https://lunar.fyi/).

### Requirements

* Python 3.6+

### Running the server

```sh
# Installs dependencies and runs the server
make

# Runs the server without installing dependencies
make run

# If IPv6 is not available use HOST
make run HOST=0.0.0.0

# Listen on another port using the PORT variable
make run PORT=8080
```

---

### Implementing light sensor reading

The file `lunarsensor.py` contains a server that reads [lux](https://en.wikipedia.org/wiki/Lux) values using the [`read_lux()`](lunarsensor.py#L53-L57) function at the bottom of the file.

Your actual sensor reading logic should be written in that function.

#### Testing the server

* Check if one-shot lux reading works

```sh
❯ curl lunarsensor.local/sensor/ambient_light

{"id":"sensor-ambient_light", "state":"0 lx", "value":0.000000}
```

* Check if the EventSource is sending lux values every 2 seconds

```sh
❯ curl -N lunarsensor.local/events

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}
```

---

### Implementation examples

#### Reading from a [BH1750](https://learn.adafruit.com/adafruit-bh1750-ambient-light-sensor) I²C sensor

```sh
pip3 install adafruit-circuitpython-bh1750
```

```python
# Do the sensor reading logic below

import board
import adafruit_bh1750

i2c = board.I2C()
sensor = adafruit_bh1750.BH1750(i2c)

def dynamic_adjust_resolution(lux):
    if lux > 300:
        sensor.resolution = adafruit_bh1750.Resolution.LOW
    elif lux > 20:
        sensor.resolution = adafruit_bh1750.Resolution.MEDIUM
    else:
        sensor.resolution = adafruit_bh1750.Resolution.HIGH

async def read_lux():
    lux = sensor.lux
    dynamic_adjust_resolution(lux)

    return lux
```

#### Reading from a [VEML7700](https://learn.adafruit.com/adafruit-veml7700) I²C sensor

```sh
pip3 install adafruit-circuitpython-veml7700
```

```python
# Do the sensor reading logic below

import board
import adafruit_veml7700

i2c = board.I2C()
sensor = adafruit_veml7700.VEML7700(i2c)

def dynamic_adjust_resolution(lux):
    if lux > 300:
        sensor.light_integration_time = adafruit_veml7700.ALS_25MS
        sensor.light_gain = adafruit_veml7700.ALS_GAIN_1_8
    elif lux > 100:
        sensor.light_integration_time = adafruit_veml7700.ALS_50MS
        sensor.light_gain = adafruit_veml7700.ALS_GAIN_1_4
    elif lux > 20:
        sensor.light_integration_time = adafruit_veml7700.ALS_100MS
        sensor.light_gain = adafruit_veml7700.ALS_GAIN_1
    elif lux > 10:
        sensor.light_integration_time = adafruit_veml7700.ALS_200MS
        sensor.light_gain = adafruit_veml7700.ALS_GAIN_1
    else:
        sensor.light_integration_time = adafruit_veml7700.ALS_400MS
        sensor.light_gain = adafruit_veml7700.ALS_GAIN_2

async def read_lux():
    lux = sensor.lux
    dynamic_adjust_resolution(lux)

    return lux
```

#### Reading from a [HomeAssistant](https://developers.home-assistant.io/docs/api/rest/) lux sensor

```python
# Do the sensor reading logic below

HOME_ASSISTANT_URL = "http://homeassistant.local:8123"  # Replace with your HomeAssistant server URL
TOKEN = "your.jwt.token"  # Replace with your long-lived HomeAssistant API token
SENSOR_ENTITY_ID = "sensor.living_room_ambient_light"  # Replace with your sensor entity id

async def read_lux():
    async with CLIENT.get(f"{HOME_ASSISTANT_URL}/api/states/{SENSOR_ENTITY_ID}", headers={"Authorization": f"Bearer {TOKEN}"}) as response:
        sensor = await response.json()
        if not json:
            return None

        return float(sensor["state"])
```

---

### Pointing Lunar to the sensor server

Lunar expects to find the sensor at the `lunarsensor.local` address by default.

This can be changed using the `defaults` command on the Mac where Lunar is running.

There are three settings that affect where Lunar looks for the sensor:

- `sensorHostname` set by default to `lunarsensor.local`
- `sensorPort` set by default to `80`
- `sensorPathPrefix` set by default to `/`

For example, if you would like to have Lunar listen for sensor events at `homeassistant.local:8123/lunar/events` you would run the following commands:

```sh
defaults write fyi.lunar.Lunar sensorHostname homeassistant.local
defaults write fyi.lunar.Lunar sensorPort 8123
defaults write fyi.lunar.Lunar sensorPathPrefix /lunar
```
