# Quercus — planejamento

**Status:** protótipo pessoal / dogfooding.  
**Primeiro cenário:** preparação real para o CACD.  
**Canal inicial:** Telegram.  
**Objetivo:** provar que um agente com memória persistente consegue aprender, ao longo de meses, como uma pessoa estuda — e usar esse aprendizado para ajudá-la a se preparar melhor.

Versão para terceiros, monetização, multiusuário, infraestrutura comercial, LGPD, marketplace, mobile, WhatsApp: **fora do horizonte desta versão**. A possibilidade existe apenas como hipótese futura e não deve ditar decisões de arquitetura agora.

---

## 1. O ciclo único a provar

```text
Quercus observa
    ↓
Quercus registra
    ↓
Quercus lembra
    ↓
Quercus consolida
    ↓
Quercus utiliza o que aprendeu
    ↓
a próxima decisão melhora
```

Tudo o que não serve para provar este ciclo é secundário.

---

## 2. Princípios técnicos

### 2.1 Memória não é histórico

```text
mensagem ≠ evento ≠ observação ≠ inferência ≠ candidato a memória ≠ memória consolidada
```

### 2.2 O LLM não é o banco de dados

O modelo interpreta e raciocina. O estado real fica estruturado.

```text
LLM → tools → domínio Quercus → SQLite
```

### 2.3 LLM não fará aritmética de agenda

Tempo, duração, recorrência, conflitos: determinísticos.

O LLM decide prioridades. O código decide encaixes.

### 2.4 Proveniência obrigatória

Categorias mínimas de origem:

```text
USER_EXPLICIT
USER_OBSERVED
SYSTEM_OBSERVED
AGENT_DERIVED
DOCUMENT_TRUSTED
DOCUMENT_UNTRUSTED
TOOL_RESULT
```

Conteúdo externo não pode declarar coisas sobre o aluno.

---

## 3. Tipos de memória

- **Episódica** — o que aconteceu.
- **Semântica** — informação relativamente estável sobre o aluno.
- **Inferencial** — padrão detectado pelo sistema. Sempre com `confidence`, `evidence[]`, `created_at`, `last_validated_at`.
- **Procedural** — o que Quercus aprende sobre como ajudar. Só depois que a memória básica estiver funcionando.

Estado operacional (prova alvo, ciclo atual, meta semanal) **não** é memória de longo prazo.

---

## 4. Modelo de dados

### `events`

Registra tudo o que aconteceu. É o **registro histórico canônico**.

```text
id
user_id
event_type      — STUDY_STARTED, STUDY_COMPLETED, STUDY_SKIPPED, PLAN_CREATED,
                  PLAN_CHANGED, QUESTION_RESULT, USER_CORRECTION,
                  USER_PREFERENCE, MEMORY_CREATED, MEMORY_UPDATED, MEMORY_REVOKED, ...
timestamp
source_type
source_id
payload_json
created_at
```

### `study_sessions`

```text
id
user_id
subject
topic
planned_minutes
actual_minutes
planned_at
started_at
finished_at
status          — planned | completed | partial | skipped | cancelled
source
notes
```

### `memories`

```text
id
user_id
memory_type     — episodic | semantic | inferential | procedural
statement
status          — candidate | active | superseded | archived | rejected | revoked | expired
confidence
importance
created_at
updated_at
last_confirmed_at
expires_at
supersedes_id
source_origin
```

### `memory_evidence`

```text
memory_id
event_id
weight
relationship
```

Toda inferência carrega suas evidências.

---

## 5. Pipeline de memória

### Light — durante o uso

- Extrai observações estruturadas;
- Normaliza, deduplica;
- Não altera memória consolidada.

### REM — 1x/dia

- Encontra recorrências;
- Deteta conflitos;
- Reforça ou enfraquece candidatos;
- Não altera memória consolidada diretamente.

### Deep — 1x/semana, ou `/quercus consolidate`

- Avalia candidatos;
- Consulta evidências;
- Decide: promote, fundir, substituir, rejeitar, manter candidato.

---

## 6. Gate de promoção (determinístico)

O LLM não promove sozinho. Antes:

```text
confidence >= threshold
AND evidence_count >= threshold
AND source_diversity >= threshold
AND não contradita por evidência recente
```

Valores iniciais serão calibrados no uso.

---

## 7. USER_EXPLICIT

Se o aluno disser algo a lembrar diretamente (ex.: "Não quero estudar no almoço"), entra como `USER_EXPLICIT` mesmo sem gate. Continua guardando origem, timestamp, e permite correção/supersessão.

---

## 8. Supersessão e rollback

- Memória anterior não é apagada — vai para `superseded`;
- Toda memória nova substitui a antiga mantendo trilha;
- Rollback via `audit_log`;
- Memória nunca desaparece sem registro.

---

## 9. Auditabilidade

O sistema deve conseguir responder:

> Por que você acha isso sobre mim?

Resposta esperada:

```text
Memória: "História tende a funcionar melhor pela manhã."
Confiança: 82%

Evidências
- 10/09 — 45 planejados / 45 realizados
- 12/09 — 45 planejados / 50 realizados
- 15/09 — 45 planejados / 43 realizados
- 16/09 — sessão noturna parcialmente concluída

Criada: 16/09
Última revisão: 17/09
```

---

## 10. Planning

O plano é estruturado, não Markdown solto.

```text
study_plan
  └── study_plan_items (subject, topic, duration, priority, deadline, reason, status, source)
```

### Adaptação diária

Ao final do dia: `planejado → realizado → diferença → replanejamento`.

Quercus **não** move tudo que foi perdido para amanhã. Decide entre:

```text
adiar | redistribuir | reduzir | cancelar | substituir | manter
```

---

## 11. Telegram como adapter

```text
Telegram Update
   ↓
telegram_adapter
   ↓
QuercusMessage
   ↓
Application Service → Agent
   ↓
QuercusResponse
   ↓
telegram_adapter
```

Nenhuma regra de negócio dentro do bot.

### Comandos administrativos mínimos

```text
/start   /new   /status   /today   /week
/memory  /memory why   /consolidate
```

Uso primordialmente conversacional — não exigir sintaxe.

---

## 12. Contexto do agente

Prompt montado dinamicamente:

```text
SYSTEM
+ IDENTITY
+ VOICE
+ estado atual
+ memórias relevantes
+ plano atual
+ eventos recentes relevantes
+ pedido do usuário
```

IDENTITY/VOICE carregam o que precisa. ORIGIN **não** vai no prompt de turno.

---

## 13. Segurança da memória

Nunca persistir automaticamente: `API_KEY`, `SECRET`, `PASSWORD`, `TOKEN`, `JWT`, `PRIVATE_KEY`.

Dados sensíveis acidentalmente recebidos são excluídos do pipeline.

---

## 14. Memory poisoning

Conteúdo vindo de web, PDF, RAG, tool, e-mail ou documento não pode declarar coisas sobre o aluno.

Somente evidências autorizadas alteram o perfil pessoal.

---

## 15. Modelos

Três workloads (não amarrados a um fornecedor):

```text
chat
extração
consolidação
```

Provider abstrato (NVIDIA, OpenAI-compatible, OpenRouter, local). Trocar de modelo não pode perder:

- histórico;
- memória;
- métricas;
- planejamento;
- conhecimento adquirido.

Inteligência acumulada mora nos **dados e na memória**, não nos pesos.

---

## 16. Embeddings

Provider abstrato (`EmbeddingProvider`). Substituível.

Busca híbrida quando fizer sentido:

```text
BM25/FTS5 + similaridade vetorial + recência + importância
```

---

## 17. Deploy mínimo

- Python 3.13
- PydanticAI
- SQLite (arquivo `quercus.db`)
- Docker Compose em VPS pequena
- Backup diário com retenção
- Restore testado de verdade antes de ser considerado pronto

---

## 18. Observabilidade

Log estruturado:

```text
request_id | user_id | session_id | model | latency
tool | tokens | memory_reads | memory_writes
consolidation_id | error
```

Sem segredos, sem conteúdo sensível.

---

## 19. Cron inicial

```text
noite:  fechar eventos pendentes → REM → backup
semana: Deep consolidation (ou /quercus consolidate)
Light:  durante o uso
```

---

## 20. Evals iniciais

Cenários MEM-01 a MEM-06 (mínimo):

- **MEM-01** — fato dito explicitamente é persistido como preferência.
- **MEM-02** — ocorrência isolada vira evento, não vira preferência.
- **MEM-03** — recorrência sustentada gera candidato.
- **MEM-04** — nova declaração contradizendo memória anterior marca superseded.
- **MEM-05** — PDF não consegue injetar "preferência" no perfil.
- **MEM-06** — pergunta "por quê" retorna resposta ancorada em evidências reais.

---

## 21. Métricas pessoais

Não medir: número de mensagens, DAU, tempo dentro do app, streak artificial.

Medir:

```text
aderência ao plano
horas planejadas / realizadas
taxa de conclusão
correções de memória
memórias revogadas
memórias utilizadas
retrieval relevante
alterações de plano aceitas / revertidas
```

Métrica central experimental:

> Plan Adherence Improvement — os planos produzidos depois de algumas semanas de aprendizado são mais executáveis que os do início?

---

## 22. Definition of Done

O ciclo único está provado quando, depois de algum tempo acompanhando a preparação real:

- [ ] converso com Quercus pelo Telegram de forma persistente;
- [ ] identidade interna independe do canal;
- [ ] reiniciar o serviço não perde estado;
- [ ] sessões de estudo são registradas estruturadamente;
- [ ] existe distinção entre evento e memória;
- [ ] existe distinção entre fato e inferência;
- [ ] toda memória consolidada tem proveniência;
- [ ] toda inferência tem pelo menos uma evidência;
- [ ] conteúdo externo não pode contaminar memória pessoal;
- [ ] candidatos podem existir sem virar memória;
- [ ] consolidação roda periodicamente;
- [ ] promotion gate existe fora do LLM;
- [ ] memórias podem ser superseded;
- [ ] memórias podem ser revogadas;
- [ ] alterações são auditáveis;
- [ ] existe rollback;
- [ ] retrieval funciona entre sessões;
- [ ] plano diário é estruturado;
- [ ] execução altera o planejamento posterior;
- [ ] existe conjunto automatizado de evals;
- [ ] backup é automático;
- [ ] restore foi efetivamente testado;
- [ ] aplicação roda continuamente na VPS;
- [ ] nenhum segredo é persistido em memória ou log;
- [ ] o comportamento permanece coerente com `docs/IDENTITY.md`;
- [ ] a personalidade inspira-se na origem sem personificar José Ferreira de Carvalho.

---

## 23. Decisões em aberto

Itens que ainda não foram decididos (e não precisam ser agora):

- formato exato das observações Light;
- pesos iniciais da prioridade de estudo;
- limiares exatos do promotion gate;
- se REM roda em processo separado ou in-process;
- chaveamento de modelos por workload.

Decidem-se quando o ciclo estiver rodando e houver dados reais.

---

## 24. Fora do horizonte

Sem compromisso para esta versão:

- lançamento público;
- usuários externos;
- monetização;
- multiusuário;
- LGPD formal;
- suporte / SLA;
- aplicativo mobile;
- WhatsApp;
- marketplace de cursos;
- banco próprio de questões;
- integração com cursinhos;
- dashboards sofisticados;
- voice;
- infraestrutura comercial.

Se algum desses se tornar útil durante o uso real, vira decisão consciente — não antecipação.