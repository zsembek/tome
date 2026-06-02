# Single Tome image (gateway / worker / mcp — selected by command).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PYTHONIOENCODING=utf-8
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY tome ./tome
COPY api ./api
COPY mcp_server ./mcp_server
RUN pip install .

# unprivileged user (non-root) + permissions on the stage/store volumes
RUN useradd -r -u 10001 -m -d /home/tome tome \
 && mkdir -p /app/_store /app/_stage \
 && chown -R tome:tome /app
USER tome

EXPOSE 8080
# gateway by default; worker/mcp — via command override in compose
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
