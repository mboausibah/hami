# Hami API + discovery worker. Official Playwright Python image (Chromium + system deps), pinned to the
# same Playwright version as backend/requirements.txt. Build from the repository root:
#   docker build -f backend/Dockerfile -t hami .
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    HAMI_DATA_DIR=/data \
    HAMI_MODELS_DIR=/data/models \
    HAMI_PROCESSED_DIR=/data/processed

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY backend/ml backend/ml
COPY backend/models backend/models
COPY backend/docker-entrypoint.sh backend/docker-entrypoint.sh
COPY testsites testsites

RUN mkdir -p /data && chown -R pwuser:pwuser /data /app \
    && sed -i 's/\r$//' backend/docker-entrypoint.sh && chmod +x backend/docker-entrypoint.sh
USER pwuser
WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
