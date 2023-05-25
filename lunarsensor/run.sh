#!/usr/bin/with-contenv bashio
export SENSOR_ENTITY_ID=$(bashio::config 'sensor_entity_id')
uvicorn --host "0.0.0.0" lunarsensor:app