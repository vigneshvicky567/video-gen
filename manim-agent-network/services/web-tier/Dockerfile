# Thin web tier — tiny image, fits Azure App Service free F1.
FROM python:3.11-slim

WORKDIR /app
COPY services/web-tier/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/web-tier/app ./app
# Frontend is copied in at build/deploy so it can be served same-origin.
COPY frontend /frontend

ENV FRONTEND_DIR=/frontend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
