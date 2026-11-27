FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --no-deps mediapipe==0.10.21
COPY server/ server/
COPY static/ static/
ENV SAND_DATA=/app/data MPLCONFIGDIR=/tmp/mpl
EXPOSE 8091
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8091"]
