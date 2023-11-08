FROM python:3.12-slim-bookworm

WORKDIR /opt/besim

COPY . .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "app.py" ]
