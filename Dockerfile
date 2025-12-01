# Use the official Python 3.13 image as the base
FROM python:3.13.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies (if any)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# ---------- ENV CONFIG ----------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# ---------- RUN ----------
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "10", "--ws-ping-timeout", "60"]