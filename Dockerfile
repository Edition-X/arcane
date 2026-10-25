# syntax=docker/dockerfile:1

# Arcane is installed from the wheel this repository builds, never from source.
# The image, the PyPI release and the GitHub release asset are then provably the
# same bytes, and the image needs no git history, no build toolchain and no
# compiler. Build the wheel first:
#
#   uv build --out-dir dist
#   docker build -t arcane .

FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_NO_CACHE=1 \
    ARCANE_HOME=/data/.arcane

COPY dist/*.whl /tmp/dist/

# Exactly one wheel is expected. A stale dist/ holding several is a build error,
# not a coin toss over which one gets installed.
RUN set -eux; \
    test "$(find /tmp/dist -name '*.whl' | wc -l)" -eq 1; \
    uv pip install --system --no-cache /tmp/dist/*.whl; \
    rm -rf /tmp/dist; \
    arcane --version; \
    useradd --uid 1000 --user-group --home-dir /data --no-create-home --shell /usr/sbin/nologin arcane; \
    mkdir -p /data/.arcane; \
    chown -R arcane:arcane /data

# The server never needs root, and running as root would leave root-owned files
# in a bind-mounted vault. Pass --user "$(id -u):$(id -g)" to match the owner
# of a host directory that is not UID 1000.
USER arcane

VOLUME ["/data/.arcane"]

ENTRYPOINT ["arcane", "mcp"]
