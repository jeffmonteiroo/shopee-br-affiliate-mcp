FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -c requirements.lock . \
    && useradd --uid 10001 --create-home mcp \
    && mkdir /app/data && chown mcp:mcp /app/data
COPY examples ./examples
COPY run.py ./run.py
USER mcp
ENTRYPOINT ["python", "/app/run.py"]

FROM runtime AS remote
ENV SHOPEE_VERIFIED_PROFILE=/app/examples/profile.official.json MCP_STATE_DB=/app/data/oauth.sqlite3
EXPOSE 8765
CMD ["--transport", "oauth-http", "--port", "8765"]

FROM runtime AS stdio
CMD ["--mode", "fixture"]
