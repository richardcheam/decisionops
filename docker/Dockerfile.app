FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/commerce-venv UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
RUN pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --only-group commerce --no-python-downloads --python /usr/local/bin/python
COPY decisionops ./decisionops
COPY data/commerce ./data/commerce
COPY migrations ./migrations
COPY alembic.ini .python-version ./
RUN useradd --uid 10001 --create-home commerce
USER 10001:10001
ENV PATH="/opt/commerce-venv/bin:$PATH"
CMD ["python", "-B", "-m", "uvicorn", "decisionops.commerce.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
