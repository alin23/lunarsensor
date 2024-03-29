# Home Assistant Add-on: Lunar Sensor

Ambient light sensor that can send data to the **[🌕 Lunar](https://lunar.fyi/)** macOS app for controlling monitor brightness automatically.

## Installation

Follow these steps to get the add-on installed on your system:

[![Open your Home Assistant instance and show the Supervisor add-on store.](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/)

![adding the lunarsensor repo to HomeAssistant addons](https://files.lunar.fyi/ha-addon-lunar-repo-adding.png)


## How to use

This add-on requires configuration for knowing where to fetch the lux data from:

1. Click on the "Configuration" tab.
2. Type in the entity ID of the lux sensor into the `sensor_entity_id` field.
3. Click the "SAVE" button.

## Configuration

Add-on configuration:

```yaml
sensor_entity_id: "sensor.lux"
```

### Option: `sensor_entity_id` (required)

Set it to the `entity_id` of the lux sensor you want to use for adapting monitor brightness.

## Lunar app configuration

Since [v6.2.4](https://lunar.fyi/changelog#6_2_4), Lunar will automatically connect to this addon if it's available on `homeassistant.local:8899`.

If the HomeAssistant instance is available on a different hostname, configure Lunar by running the following commands on your Mac:

```sh
defaults write fyi.lunar.Lunar sensorHostname your-homeassistant-hostname
defaults write fyi.lunar.Lunar sensorPort 8899
```

## Troubleshooting

* Check if one-shot lux reading works

```sh
❯ curl homeassistant.local:8899/sensor/ambient_light

{"id":"sensor-ambient_light", "state":"0 lx", "value":0.000000}
```

* Check if the EventSource is sending lux values every 2 seconds

```sh
❯ curl -N homeassistant.local:8899/events

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}

event: state
data: {"id": "sensor-ambient_light", "state": "400.0 lx", "value": 400.0}
```


## Support

Got questions?

You have several options to get them answered:

- The [Lunar Discord Chat Server](https://discord.gg/dJPHpWgAhV).
- The [Github repository](https://github.com/alin23/lunarsensor) of the **addon**.
- The [Github repository](https://github.com/alin23/Lunar) of the **app**.
- The [FAQ section](https://lunar.fyi/faq) of the app
