# The pricing engine. It holds no wallet keys.
# Build from the repository root:  docker build --file services/engine/Dockerfile .

FROM python:3.10.8-slim-bullseye AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# Third-party dependencies first: exactly the lock file, each pinned by hash. This
# layer is rebuilt only when the lock changes.
COPY services/engine/requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --no-deps --requirement /tmp/requirements.txt
COPY libs/core /src/libs/core
COPY services/engine /src/services/engine
RUN pip install --no-deps /src/libs/core /src/services/engine && pip check

FROM python:3.10.8-slim-bullseye
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin autolister
COPY --from=build /opt/venv /opt/venv
COPY config/strategy.yaml config/accounts.yaml /etc/autolister/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUTOLISTER_STRATEGY_FILE=/etc/autolister/strategy.yaml \
    AUTOLISTER_ACCOUNTS_FILE=/etc/autolister/accounts.yaml
USER 10001
ENTRYPOINT ["autolister-engine"]
