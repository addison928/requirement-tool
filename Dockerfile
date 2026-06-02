FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ backend/

# Copy frontend HTML and JS files
COPY *.html .
COPY *.js .

EXPOSE 8000

# Start server (Supabase REST API mode, no local DB needed)
CMD cd backend && PYTHONIOENCODING=utf-8 uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
