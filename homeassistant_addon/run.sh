#!/usr/bin/with-contenv bashio
export SENSOR_ENTITY_ID=$(bashio::config 'sensor_entity_id')
export COLOR_ENTITY_ID=$(bashio::config 'color_entity_id' '')
exec python3 /lunarsensor.py
