# Wraps the official LiteLLM image to fix a real, reproducible bug on this
# project's ARM64 Docker environment: the image ships cryptography==50.0.0,
# whose compiled extension crashes with SIGILL on import
# (cryptography.hazmat.primitives.ciphers.base) -- the exact same root
# cause hit twice before in this project (the `mcp` SDK's transitive dep,
# app/mcp_server.py; and Langfuse's dependency chain). Pinning to 43.0.3
# fixes it every time. The base image ships no pip, so ensurepip bootstraps
# one first.
FROM ghcr.io/berriai/litellm:main-latest
RUN /app/.venv/bin/python -m ensurepip --upgrade \
    && /app/.venv/bin/python -m pip install --force-reinstall --no-deps "cryptography==43.0.3" \
    && /app/.venv/bin/python -m pip uninstall -y pip
