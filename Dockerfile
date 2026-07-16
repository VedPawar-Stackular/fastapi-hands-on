# Base image: matches .python-version (3.12). slim = no compilers/docs, ~150MB vs ~1GB
FROM python:3.12-slim

# All later paths relative to this. Also where `uv run` looks for pyproject.toml
WORKDIR /app

# Grab uv binary from its official image instead of pip-installing it — faster, no bootstrap
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy ONLY dependency manifests first (caching trick — see below)
COPY pyproject.toml uv.lock ./

# --frozen: fail if uv.lock out of sync, don't silently rewrite it (reproducible build)
# --no-install-project: install deps only — src/ isn't copied in yet, nothing to install
RUN uv sync --frozen --no-install-project

# Now bring in actual code. This layer busts on every code change; deps layer above stays cached
COPY src/ ./src/

# Install the project itself now that src/ exists
RUN uv sync --frozen

EXPOSE 8000

# --app-dir points uvicorn at src/my_app as import root — required because
# resolved_app.py does `from config import settings` (flat import, no package prefix).
# Same trick your pyproject.toml uses for pytest via pythonpath=["src/my_app"]
CMD ["uv", "run", "uvicorn", "app:app", "--app-dir", "src/my_app", "--host", "0.0.0.0", "--port", "8000"]
#CMD ["uv", "run", "uvicorn", "resolved_app:app", "--app-dir", "src/my_app", "--host", "0.0.0.0", "--port", "8000"]