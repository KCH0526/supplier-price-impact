FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
# Optional: networks with an SSL-inspecting proxy can pass the company CA as a
# build secret (it is only mounted for this step and never stored in the image):
#   docker build --secret id=corp_ca,src=/path/to/company-ca.crt .
RUN --mount=type=secret,id=corp_ca,required=false \
    if [ -f /run/secrets/corp_ca ]; then export PIP_CERT=/run/secrets/corp_ca; fi \
    && pip install --no-cache-dir -r requirements-lock.txt \
    && useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8501
# 0.0.0.0 is inside the container only; docker-compose publishes it on 127.0.0.1.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
