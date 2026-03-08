FROM python:3.13.2-slim-bookworm AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

FROM python-base AS builder

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.txt

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

COPY . .

FROM python-base AS dev

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements.txt -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM python-base AS runtime

RUN apt-get update \
 && apt-get install --yes --no-install-recommends \
    curl \
    ca-certificates \
    jq \
    procps \
    netcat-openbsd \
 && rm -rf /var/lib/apt/lists/*
 
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/app --shell /usr/sbin/nologin app

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

RUN mkdir -p /app/workspaces \
    && touch /app/workspaces/.dockerkeep \
    && chown -R app:app /app/workspaces

USER app

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
