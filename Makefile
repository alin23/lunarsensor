.EXPORT_ALL_VARIABLES:
all: install run

install:
	pip install -r requirements.txt

run: SENSOR_DEBUG=0
run:
	sudo -E uvicorn --host 0.0.0.0 --port 80 --reload lunarsensor:app
