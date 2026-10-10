# Imagem base do Python
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Correr como utilizador não-root (a pasta da BD tem de lhe pertencer)
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/database /app/instance \
    && chown -R appuser:appuser /app/database /app/instance
USER appuser

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
