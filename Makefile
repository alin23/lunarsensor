.EXPORT_ALL_VARIABLES:
all: install run

install:
	pip install -r requirements.txt

run: SENSOR_DEBUG=0
run: PORT=80
run: HOST=::
run: UVICORN=$(shell which uvicorn)
run:
	test -f /bin/launchctl && sudo launchctl bootout system/org.apache.httpd 2>/dev/null || true
	sudo -E $(UVICORN) --host $(HOST) --port $(PORT) --reload lunarsensor:app
