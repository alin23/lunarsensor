.EXPORT_ALL_VARIABLES:
all: run

# Dependencies are managed by uv (https://docs.astral.sh/uv/): `uv sync` creates .venv
# with a compatible Python (downloads one when needed) and the locked dependencies.
install:
	uv sync

# Lunar looks for the sensor on port 80, which needs root; the server also announces
# itself over mDNS (_lunarsensor._tcp) so Lunar finds it right away.
run: PORT=80
run: HOST=::
run: install
	test -f /bin/launchctl && sudo launchctl bootout system/org.apache.httpd 2>/dev/null || true
	sudo -E .venv/bin/lunarsensor

# Rootless alternative on a high port (set the same port in Lunar's sensor settings).
run-user: PORT=8080
run-user: HOST=::
run-user: install
	.venv/bin/lunarsensor
