FROM python:3.12-slim

WORKDIR /app

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy dependency configuration
COPY pyproject.toml .

# Install dependencies using uv
RUN uv sync

# Copy Flask application files
COPY flask_app.py ./
COPY opsagent/ ./opsagent/
COPY .env .

# Expose port (documentation only - actual port set via WEBSITES_PORT)
EXPOSE 8000

# Start Flask application using Gunicorn
CMD ["uv", "run", "gunicorn", "-b", "0.0.0.0:8000", "-w", "4", "flask_app:app"]
