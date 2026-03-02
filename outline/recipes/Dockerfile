FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn jinja2 python-multipart
COPY . .
RUN mkdir -p /data
VOLUME /data
ENV DB_PATH=/data/recipes.db
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
