FROM python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
RUN apk add --no-cache krb5-libs=1.22.3-r0 zlib=1.4-r0
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock && python -m pip uninstall -y pip
COPY app.py .
COPY serve_dashboard_socket.py .
COPY static ./static
COPY services/private-fitness-mcp/fitness ./fitness
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 8787
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8787","--no-access-log","--log-level","critical","--no-proxy-headers"]
