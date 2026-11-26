# ---------------------------------------------------------------- 1. interface React
FROM node:22-slim AS web
# Certificats d'entreprise (proxy TLS type Zscaler) pour npm.
COPY --from=certs . /certs/
RUN cat /certs/*.crt > /certs/corp.pem 2>/dev/null || true
ENV NODE_EXTRA_CA_CERTS=/certs/corp.pem
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. API + fichiers statiques
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# Certificats d'entreprise (proxy TLS type Zscaler), copiés dans ./certs par install.sh.
COPY --from=certs . /usr/local/share/ca-certificates/
RUN update-ca-certificates >/dev/null
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY govadmin ./govadmin
COPY --from=web /web/dist ./govadmin/webapp

EXPOSE 8788
CMD ["uvicorn", "govadmin.main:app", "--host", "0.0.0.0", "--port", "8788", "--workers", "1", "--no-access-log"]
