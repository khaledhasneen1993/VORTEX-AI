FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY vortex ./vortex
RUN pip install --no-cache-dir .
RUN useradd -r -u 10001 vortex && mkdir -p /app/data && chown -R vortex:vortex /app/data
USER vortex
ENTRYPOINT ["vortex"]
CMD ["paper"]
