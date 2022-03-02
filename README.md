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

# Running the server without installing dependencies
make run
```

---

### Implementing light sensor reading

The file `lunarsensor.py` contains a server that reads [lux](https://en.wikipedia.org/wiki/Lux) values using the [`read_lux()`](lunarsensor.py#L40) function at the bottom of the file.

Your actual sensor reading logic should be written in that function.

#### Testing the server

* Check if one-shot lux reading works
    * `curl lunarsensor.local/sensor/ambient_light_tsl2561`
* Check if the EventSource is sending lux values every 2 seconds
    * `curl -N lunarsensor.local/events`

#### Example of reading from a [BH1750](https://learn.adafruit.com/adafruit-bh1750-ambient-light-sensor) I2C sensor

1. Install the Adafruit BH1750 library
    - `pip3 install adafruit-circuitpython-bh1750`
2. Replace the `read_lux()` function with the following code at the bottom of the [`lunarsensor.py`](lunarsensor.py#L40) file

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