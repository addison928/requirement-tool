FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r backend/requirements.txt
ENV PYTHONIOENCODING=utf-8
EXPOSE 8000
CMD cd backend && python3 seed.py 2>/dev/null; \
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
