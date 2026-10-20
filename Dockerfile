# The terminal app and the MCP server, with Playwright's Chromium preinstalled.
#   docker run --rm -e GEMINI_API_KEY -e JEV_API_KEY ghcr.io/haneeshraj/business-insights-v2 analyze https://example.com
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv build --wheel --out-dir /dist

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
COPY --from=build /dist /dist
RUN uv pip install --system "$(ls /dist/*.whl)[mcp]" \
    && playwright install --with-deps chromium \
    && rm -rf /dist /root/.cache
# Results go to /data, which a run can mount to keep them.
WORKDIR /data
RUN useradd --create-home bi2 && chown bi2 /data
USER bi2
ENTRYPOINT ["bi2"]
CMD ["--help"]
