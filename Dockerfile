# Marketing pipeline — FastAPI service in Docker.
# The container talks to Ollama on the host (set OLLAMA_BASE_URL); it does
# not bundle any model. The checkpoint DB (step7.db) lives in the working
# directory — mount a volume if you want runs to survive a rebuild.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY knowledge_base/ ./knowledge_base/

ENV PYTHONPATH=/app/src
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434

EXPOSE 8000

CMD ["uvicorn", "marketing_pipeline.api:app", "--host", "0.0.0.0", "--port", "8000"]
