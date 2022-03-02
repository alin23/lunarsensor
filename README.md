# [Lunar](https://github.com/alin23/Lunar) Sensor

## Server that implements a custom Ambient Light Sensor for adapting monitor brightness with Lunar

### Requirements

* Python 3.6+
* Access to binding port `80`

### Running the server

```sh
# Installs dependencies and runs the server
make

# OR

# Runs the server without installing dependencies
make run
```

---

### Implementing light sensor reading

The file `lunarsensor.py` contains a server that reads [lux](https://en.wikipedia.org/wiki/Lux) values using the [`read_lux()`](lunarsensor.py#L40) function at the bottom of the file.

Your actual sensor reading logic should be written in that function.

#### Testing the server

* Check if one-shot lux reading works

```json
❯ curl lunarsensor.local/sensor/ambient_light_tsl2561

{"id":"sensor-ambient_light_tsl2561", "state":"0 lx", "value":0.000000}
```

* Check if the EventSource is sending lux values every 2 seconds

```json
❯ curl lunarsensor.local/events

event: state
data: {"id": "sensor-ambient_light_tsl2561", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light_tsl2561", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light_tsl2561", "state": "400.0 lx", "value": 400.0}
```

---

### Implementation examples

#### Reading from a [BH1750](https://learn.adafruit.com/adafruit-bh1750-ambient-light-sensor) I2C sensor

1. Install the Adafruit BH1750 library
    - `pip3 install adafruit-circuitpython-bh1750`
2. Replace the `read_lux()` function with the following code at the bottom of the [`lunarsensor.py`](lunarsensor.py#L37-L41) file

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

#### Reading from a [VEML7700](https://learn.adafruit.com/adafruit-veml7700) I2C sensor

1. Install the Adafruit VEML7700 library
    - `pip3 install adafruit-circuitpython-veml7700`
2. Replace the `read_lux()` function with the following code at the bottom of the [`lunarsensor.py`](lunarsensor.py#L37-L41) file

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

---

### Pointing Lunar to the sensor server

Lunar expects to find the sensor at the `lunarsensor.local` address.

Since the sensor server can be run anywhere (e.g. Raspberry Pi, NAS, PC etc), changing the hostname might not be desirable. 

You can map the hostname to the sensor server IP using the `/etc/hosts` file on the Mac device where Lunar is running.


#### Example of `/etc/hosts` change at the end
```diff
##
# Host Database
#
# localhost is used to configure the loopback interface
# when the system is booting.  Do not change this entry.
##
127.0.0.1   localhost
255.255.255.255 broadcasthost
::1             localhost

+ # Added for Lunar sensor server
+ 192.168.0.203    lunarsensor.local
```