FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY pyproject.toml ./
COPY otp_auth ./otp_auth
RUN pip install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH
RUN useradd -r -u 10001 app
COPY --from=builder /opt/venv /opt/venv
USER app
EXPOSE 8000
CMD ["uvicorn", "otp_auth.web.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
