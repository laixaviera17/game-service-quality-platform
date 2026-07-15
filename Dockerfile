FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY dashboard.html ./dashboard.html
COPY scripts ./scripts

# API 和 Worker 均不需要以 root 权限访问容器内资源。
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
