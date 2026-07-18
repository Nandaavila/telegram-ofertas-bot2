FROM python:3.11-slim

WORKDIR /app

# Copia só o requirements primeiro para aproveitar cache do Docker
# (só reinstala dependências se o requirements.txt mudar, não a cada
# alteração de código — isso acelera muito o rebuild da imagem).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
