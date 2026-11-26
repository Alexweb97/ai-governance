# Presidio Analyzer avec le modèle spaCy français (l'image officielle ne contient que l'anglais).
FROM mcr.microsoft.com/presidio-analyzer:latest

# Certificats d'entreprise (proxy TLS type Zscaler), copiés dans ./certs par install.sh :
# sans eux, le téléchargement du modèle échoue sur un poste d'entreprise.
USER root
COPY --from=certs . /usr/local/share/ca-certificates/
RUN update-ca-certificates >/dev/null
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt
USER presidio

RUN python -m spacy download fr_core_news_lg

COPY analyzer-conf.yaml /app/conf/analyzer-conf.yaml
COPY nlp-conf.yaml /app/conf/nlp-conf.yaml
COPY recognizers-conf.yaml /app/conf/recognizers-conf.yaml

# Lus par l'application Presidio au démarrage.
ENV ANALYZER_CONF_FILE=/app/conf/analyzer-conf.yaml \
    NLP_CONF_FILE=/app/conf/nlp-conf.yaml \
    RECOGNIZER_REGISTRY_CONF_FILE=/app/conf/recognizers-conf.yaml
