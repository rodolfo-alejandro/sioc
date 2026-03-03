FROM python:3.11-slim

WORKDIR /app

# PyMySQL es puro Python, no hace falta gcc ni libmysqlclient-dev
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar aplicación
COPY . .

# Crear directorio para uploads
RUN mkdir -p instance/uploads

# Exponer puerto
EXPOSE 5001

# Comando por defecto
CMD ["python", "run.py"]



