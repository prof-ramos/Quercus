# Quercus — Guia de Deploy e Recuperação de Desastres

Este documento orienta o provisionamento, operação contínua, backup online e procedimentos de recuperação do Quercus em uma VPS pequena (Hetzner, DigitalOcean, Oracle Cloud, Linode, etc.).

---

## 1. Requisitos de Infraestrutura

- **Recursos mínimos**: 1 vCPU, 1 GB de RAM, 10 GB de disco SSD.
- **Sistema Operacional**: Linux (Debian 12+, Ubuntu 22.04+ ou Alpine).
- **Runtime**: Python 3.13+ (ou Docker Engine 24+ com Docker Compose v2+).
- **Rede**: Apenas saída HTTPS (porta 443) para a API do Telegram e LLMs. **Nenhuma porta de entrada pública precisa ser exposta**.

---

## 2. Variáveis de Ambiente

Crie o arquivo `.env` na raiz do projeto a partir do modelo [.env.example](file:///.env.example):

```bash
cp .env.example .env
chmod 600 .env
```

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Sim (p/ bot) | - | Token HTTP emitido pelo `@BotFather`. |
| `TELEGRAM_ALLOWED_USER_IDS` | Sim (p/ bot) | - | IDs numéricos do Telegram autorizados (ex: `123456789`). |
| `QUERCUS_USER_ID` | Não | `gabriel` | Identificador canônico do aluno. |
| `QUERCUS_DB_PATH` | Não | `/app/data/quercus.db` (Docker) ou `quercus.db` | Caminho do arquivo SQLite. |
| `QUERCUS_BACKUP_DIR` | Não | `/app/backups` (Docker) ou `backups` | Diretório de destino dos snapshots. |
| `QUERCUS_BACKUP_RETENTION_DAYS`| Não | `7` | Dias de retenção dos backups diários. |

---

## 3. Deploy com Docker Compose (Recomendado)

### 3.1. Subida do Gateway

Clone o repositório e inicie o serviço:

```bash
git clone https://github.com/prof-ramos/Quercus.git /opt/quercus
cd /opt/quercus
cp .env.example .env
# Edite o .env com seu TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_IDS

docker compose up -d --build quercus
```

Para acompanhar os logs:

```bash
docker compose logs -f quercus
```

### 3.2. Agendamento da Rotina Noturna via Cron do Host

Adicione uma entrada na crontab do host (`crontab -e`) para disparar a rotina de consolidação noturna (fechamento de eventos → REM → adaptação de plano → backup online) todos os dias às 03:00:

```cron
0 3 * * * cd /opt/quercus && docker compose run --rm quercus-nightly >> /opt/quercus/backups/nightly.log 2>&1
```

---

## 4. Deploy Nativo com Systemd

Para ambientes sem Docker, utilizando ambiente virtual Python:

### 4.1. Instalação e Preparação

```bash
sudo useradd -m -u 1000 -s /bin/bash quercus
sudo mkdir -p /opt/quercus/{data,backups}
sudo chown -R quercus:quercus /opt/quercus

sudo -u quercus git clone https://github.com/prof-ramos/Quercus.git /opt/quercus/app
cd /opt/quercus/app
python3.13 -m venv /opt/quercus/.venv
/opt/quercus/.venv/bin/pip install .
```

### 4.2. Instalação dos Serviços

Copie os arquivos de serviço da pasta `deploy/systemd/`:

```bash
sudo cp deploy/systemd/quercus.service /etc/systemd/system/
sudo cp deploy/systemd/quercus-nightly.service /etc/systemd/system/
sudo cp deploy/systemd/quercus-nightly.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now quercus.service
sudo systemctl enable --now quercus-nightly.timer
```

Verifique o status do serviço e timer:

```bash
sudo systemctl status quercus.service
sudo systemctl list-timers quercus-nightly.timer
```

---

## 5. Estratégia de Backup Online (SQLite WAL)

O Quercus utiliza o mecanismo nativo de backup online da stdlib do Python (`sqlite3.Connection.backup()`), garantindo:

1. **Zero Downtime**: O bot pode continuar respondendo e gravando eventos durante a cópia.
2. **Consistência Atômica**: O arquivo gerado reflete um ponto no tempo matematicamente íntegro, mesmo com o WAL ativo.
3. **Compactação Gzip**: Backups são compactados em `.db.gz`, economizando até 80% de espaço.
4. **Purga Automática**: Backups mais antigos que `QUERCUS_BACKUP_RETENTION_DAYS` (padrão 7 dias) são removidos automaticamente.

### 5.1. Executar Backup Manual Imediato

Via Docker Compose:
```bash
docker compose run --rm quercus python scripts/backup_db.py
```

Via CLI direta:
```bash
python scripts/backup_db.py --db-path /opt/quercus/data/quercus.db --backup-dir /opt/quercus/backups
```

---

## 6. Procedimento de Restauração e Teste de Desastre

Antes de considerar o sistema pronto para produção, a restauração foi validada pelo script automatizado `scripts/test_restore.sh`.

### 6.1. Validação de Integridade (Modo Não-Destrutivo)

Para inspecionar um backup e verificar se suas páginas e foreign keys estão 100% integras sem tocar no banco ativo:

```bash
python scripts/restore_db.py --backup-file backups/quercus_backup_20260918_030000.db.gz --verify-only
```

Saída esperada:
```text
[*] Validando backup: backups/quercus_backup_20260918_030000.db.gz
[OK] Verificação de integridade aprovada (PRAGMA integrity_check = ok)
[*] Contagem de registros por tabela restaurada:
    - events: 42 registros
    - memories: 7 registros
    - memory_evidence: 14 registros
    - study_sessions: 25 registros
    - study_plans: 6 registros
[OK] Teste concluído com sucesso em modo verify-only.
```

### 6.2. Restauração Física em Caso de Falha de Servidor

Se for necessário recriar o banco de produção a partir de um backup:

1. Pare o serviço do bot:
   ```bash
   docker compose stop quercus
   # ou: sudo systemctl stop quercus.service
   ```

2. Restaure o backup sobre o arquivo de produção:
   ```bash
   python scripts/restore_db.py \
     --backup-file backups/quercus_backup_20260918_030000.db.gz \
     --target-db /opt/quercus/data/quercus.db
   ```

3. Reinicie o serviço:
   ```bash
   docker compose start quercus
   # ou: sudo systemctl start quercus.service
   ```

### 6.3. Execução da Suíte Completa de Teste de Restauração

Para rodar a verificação automatizada completa (cria banco de teste, popula registros, gera backup online, valida integridade e testa restauração física):

```bash
./scripts/test_restore.sh
```
