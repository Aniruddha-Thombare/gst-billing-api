# Base Image
FROM python:3.11-slim

# Working Directory
WORKDIR /app

# prevents .pyc files from being generated and enables stdout logging without buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install Dependencies
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Copy Application Code
COPY ./app ./app
COPY ./migrations ./migrations  
COPY ./alembic.ini .

# Expose the Application Port
EXPOSE 8000 

# Start the Application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
