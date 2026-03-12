FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for PostGIS (GDAL/GEOS/PROJ) and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    binutils \
    gcc \
    g++ \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    proj-bin \
    libproj-dev \
    gettext \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh

COPY src/ /app/src/
COPY tests/ /app/tests/

ENV DJANGO_SETTINGS_MODULE=american_voter_directory.settings

EXPOSE 8000

ENTRYPOINT ["bash", "/app/scripts/entrypoint.sh"]
