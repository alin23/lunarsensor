# Build and publish the prebuilt Home Assistant add-on images.
#
# Without prebuilt images the Supervisor builds the add-on on the user's own machine, which
# on a Pi means a slow build and, for any dependency without a musllinux wheel, a raw cargo
# error instead of a clear failure. With `image:` set in config.yaml the install is a pull.
#
# Architectures match `arch:` in config.yaml — keep the two in step. armhf and i386 are
# deliberately excluded: Alpine/musl base with no compiler, and aiohttp/zeroconf/pydantic-core
# publish no musllinux wheels for them.
#
# ORDER MATTERS: push the images BEFORE bumping `version` in a published config.yaml. The
# Supervisor uses that version as the image tag, so a bump without a matching push makes every
# install fail on a missing tag.
#
# Requires a Docker daemon with buildx and multi-platform support, and a registry login with
# write:packages. On a Mac without Docker, point BUILD_HOST at a Linux box (a Pi 4/5 runs
# arm64 and arm/v7 natively; amd64 goes through qemu).

REGISTRY   ?= ghcr.io/alin23
NAME       ?= lunarsensor
VERSION    := $(shell sed -n 's/^version: *"\(.*\)"/\1/p' config.yaml)
ARCHES     := aarch64 amd64 armv7

# Add-on arch label -> Docker platform, and the hassio base image suffix.
PLATFORM_aarch64 = linux/arm64
PLATFORM_amd64   = linux/amd64
PLATFORM_armv7   = linux/arm/v7

BASE_aarch64 = ghcr.io/hassio-addons/base-python:17.0.0
BASE_amd64   = ghcr.io/hassio-addons/base-python:17.0.0
BASE_armv7   = ghcr.io/hassio-addons/base-python:17.0.0

# NOTE: build-<arch> and push-<arch> are deliberately NOT listed here. GNU make refuses to
# apply a pattern rule to a target declared .PHONY, so marking them phony makes `make push`
# print "Nothing to be done" and exit 0 — the recipes never run, and only the final `@echo`
# is left to claim success. That silently pushed nothing at all.
.PHONY: all build push login print-version

all: build

print-version:
	@echo $(VERSION)

# `docker login ghcr.io` with a token that has write:packages. A plain `gh auth token` is NOT
# enough unless the CLI was authorised with that scope (gh auth refresh -s write:packages).
login:
	gh auth token | docker login ghcr.io -u alin23 --password-stdin

# --pull=always is not optional. Docker treats a platform mismatch against a locally cached
# image as a warning, not an error, so a stale cache silently produces an image for the wrong
# CPU that looks correct right up until it reaches a user's machine.
build-%:
	docker buildx build \
		--platform $(PLATFORM_$*) \
		--pull \
		--build-arg BUILD_FROM=$(BASE_$*) \
		--tag $(REGISTRY)/$(NAME)-$*:$(VERSION) \
		--tag $(REGISTRY)/$(NAME)-$*:latest \
		--load \
		.

push-%:
	docker buildx build \
		--platform $(PLATFORM_$*) \
		--pull \
		--build-arg BUILD_FROM=$(BASE_$*) \
		--tag $(REGISTRY)/$(NAME)-$*:$(VERSION) \
		--tag $(REGISTRY)/$(NAME)-$*:latest \
		--push \
		.

build: $(addprefix build-,$(ARCHES))
	@echo "built $(NAME) $(VERSION) for: $(ARCHES)"

push: $(addprefix push-,$(ARCHES))
	@echo
	@echo "verifying every image is really on the registry"
	@for a in $(ARCHES); do \
		docker manifest inspect $(REGISTRY)/$(NAME)-$$a:$(VERSION) >/dev/null 2>&1 \
			|| { echo "FAIL: $(REGISTRY)/$(NAME)-$$a:$(VERSION) is not on the registry" >&2; exit 1; }; \
		echo "   $(NAME)-$$a:$(VERSION) OK"; \
	done
	@echo
	@echo "pushed $(NAME) $(VERSION) for: $(ARCHES)"
	@echo "Make the packages public in the GitHub UI on first publish, or the Supervisor"
	@echo "cannot pull them anonymously."
