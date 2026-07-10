FROM python:3.12-slim

RUN pip install --no-cache-dir devpi-server==6.13.* devpi-client==7.1.*

RUN useradd --create-home --shell /bin/bash devpi
RUN mkdir -p /data && chown devpi:devpi /data

USER devpi
WORKDIR /data

RUN devpi-server --serverdir=/data --init

EXPOSE 3141

ENTRYPOINT ["devpi-server", "--serverdir=/data", "--host=0.0.0.0", "--port=3141"]
