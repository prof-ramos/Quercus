# Quercus - Agente Pessoal para Concursos (CACD)
# Dockerfile otimizado para Python 3.13 em VPS pequena

FROM python:3.13-slim

# Evita geração de bytecode .pyc e força flush imediato de stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QUERCUS_DB_PATH=/app/data/quercus.db \
    QUERCUS_BACKUP_DIR=/app/backups

# Cria usuário não-root seguro
RUN useradd -m -u 1000 -s /bin/bash quercus

WORKDIR /app

# Instala dependências do sistema necessárias para compilação mínima (se houver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copia arquivos de configuração e código
COPY pyproject.toml /app/
COPY src/ /app/src/
COPY scripts/ /app/scripts/

# Instala a aplicação
RUN pip install .

# Cria diretórios de persistência e ajusta permissões
RUN mkdir -p /app/data /app/backups && \
    chown -R quercus:quercus /app

USER quercus

# Comando padrão inicia o bot do Telegram
CMD ["python", "-m", "quercus", "bot"]
