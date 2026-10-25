FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data WEB_DATA_DIR=/web-data
WORKDIR /app
COPY collector/ collector/
RUN useradd -r -u 10001 sammler && mkdir -p /data /web-data && chown sammler /data /web-data
USER sammler
# gesund, wenn der letzte Export weniger als 3 Stunden alt ist
HEALTHCHECK --interval=10m --timeout=10s --start-period=5m CMD python -c "import os,sys,time;sys.exit(0 if time.time()-os.path.getmtime('/web-data/meta.json')<10800 else 1)"
CMD ["python", "-m", "collector.run", "--intervall", "3600"]
