FROM python:3.13.2-slim-bookworm AS sandbox

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10002 sandbox \
    && useradd --uid 10002 --gid 10002 --create-home --shell /usr/sbin/nologin sandbox

WORKDIR /sandbox

COPY runner.py /sandbox/runner.py

USER sandbox

ENTRYPOINT ["python", "/sandbox/runner.py"]
