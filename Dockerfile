# Moteur Verifac (API et travailleur) : une seule image, deux commandes.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app
# Les dépendances d'abord : elles changent rarement, la couche reste en cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY moteur ./moteur

RUN useradd --uid 1000 --create-home docuflow && mkdir -p /app/donnees && chown docuflow /app/donnees
USER docuflow

EXPOSE 8010
CMD ["uvicorn", "moteur.api:creer_application", "--factory", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers", "--forwarded-allow-ips", "*"]
