.EXPORT_ALL_VARIABLES:
all: install run

install:
	pip install -r requirements.txt

run: SENSOR_DEBUG=0
run: PORT=80
run:
	test -f /bin/launchctl && sudo launchctl bootout system/org.apache.httpd 2>/dev/null || true
	sudo -E uvicorn --host 0.0.0.0 --port $(PORT) --reload lunarsensor:app
