# Planejamento de desenvolvimento — Quercus v0.1

**Status:** planejamento inicial
**Escopo:** versão pessoal, com arquitetura preparada para futura evolução multiusuário
**Primeiro domínio:** CACD
**Canal inicial:** Telegram
**Infraestrutura:** VPS própria
**Meta:** colocar uma versão utilizável em produção em **2 a 3 semanas**, mantendo o escopo do MVP entre aproximadamente **20 e 30 horas efetivas de desenvolvimento**.

---

## 1. Objetivo

Construir a primeira versão funcional do **Quercus**, um agente persistente de preparação para concursos que aprende progressivamente como o usuário estuda e utiliza esse conhecimento para adaptar sua preparação.

A tese do produto já definida é:

> **Quercus não sabe apenas sobre concursos. Ele aprende o concurseiro.**

O produto não pretende substituir cursinhos ou transformar-se prioritariamente em ferramenta de ensino de conteúdo. Seu foco é operar a preparação: técnica, organização, calendário, erros recorrentes, histórico e adaptação. 

O ciclo fundamental será:

```text
PLANEJAR
   ↓
EXECUTAR
   ↓
OBSERVAR
   ↓
REGISTRAR EVIDÊNCIAS
   ↓
CONSOLIDAR
   ↓
ATUALIZAR MEMÓRIA
   ↓
ADAPTAR PLANO
   └──────────────→ novo ciclo
```

Esse ciclo implementa diretamente o princípio já estabelecido de **memória antes de conteúdo**. 

---

# 2. Critério de sucesso do MVP

O MVP estará concluído quando for possível executar, de ponta a ponta, o seguinte cenário:

1. Você conversa com Quercus pelo Telegram.
2. Quercus conhece seu contexto atual de preparação.
3. Ele propõe o plano de estudo do dia.
4. Você informa posteriormente o que realmente aconteceu.
5. O sistema registra os acontecimentos como evidências, sem convertê-los automaticamente em verdades permanentes.
6. Informações relevantes podem ser recuperadas em sessões futuras.
7. Um processo de consolidação periódico identifica padrões recorrentes.
8. Padrões suficientemente sustentados são promovidos para memória persistente.
9. Quercus utiliza essas memórias ao produzir planos posteriores.
10. Quando uma memória influencia uma decisão, é possível saber:

* qual memória foi usada;
* de onde ela veio;
* quais evidências a sustentam;
* quando foi criada;
* como corrigi-la ou removê-la.

11. Mudanças importantes no plano permanecem auditáveis e reversíveis.

Se esse ciclo funcionar de forma consistente, o diferencial central do Quercus estará tecnicamente demonstrado.

---

# 3. Fora do escopo do MVP

A primeira versão **não terá**:

* fine-tuning;
* modelo próprio;
* aplicativo mobile;
* WhatsApp;
* interface web completa;
* marketplace de cursos;
* banco próprio de questões;
* substituição de TEConcursos/Aprovado;
* gamificação;
* feed;
* rede social;
* multiusuário;
* cobrança;
* assinatura;
* integração com todos os cursinhos;
* voz;
* dashboards sofisticados;
* geração extensa de aulas;
* arquitetura distribuída;
* microserviços;
* vector database externo;
* Kafka;
* Redis como requisito;
* Kubernetes;
* infraestrutura específica para eventual produto comercial.

Tudo isso fica condicionado à validação do loop central.

---

# 4. Princípios técnicos

## 4.1 Memória não é histórico

O sistema deve distinguir:

```text
mensagem
≠
evento
≠
observação
≠
inferência
≠
candidato a memória
≠
memória consolidada
```

Exemplo:

```text
Mensagem:
"Hoje não consegui estudar de manhã."

Evento:
sessão prevista de História não ocorreu.

Observação:
0 minutos realizados na janela planejada.

Inferência:
nenhuma inicialmente.

Após recorrência:
possível dificuldade de execução no período da manhã.

Candidato:
"execução matinal abaixo do planejado nas últimas semanas."

Memória:
somente se houver evidência suficiente.
```

---

## 4.2 O LLM não será o banco de dados

O modelo interpreta e raciocina.

O estado real fica armazenado de forma estruturada.

```text
LLM
 ↓
tools
 ↓
domínio Quercus
 ↓
SQLite
```

O modelo não deve precisar reler toda a conversa para descobrir:

* quantas horas você estudou;
* qual disciplina está atrasada;
* qual assunto apresenta maior erro;
* quando ocorreu determinado estudo;
* qual memória está ativa;
* quais evidências sustentam uma inferência.

---

## 4.3 LLM não fará aritmética de agenda

Tempo disponível, duração, recorrência, conflitos e distribuição de carga devem ser processados deterministicamente.

O LLM poderá decidir:

> “História do Brasil merece prioridade amanhã.”

O código determinará:

> “Há 45 minutos disponíveis entre 08h30 e 09h15.”

---

## 4.4 Proveniência obrigatória

Qualquer conhecimento persistido deverá identificar sua origem.

Categorias mínimas:

```text
USER_EXPLICIT
USER_OBSERVED
SYSTEM_OBSERVED
AGENT_DERIVED
DOCUMENT_TRUSTED
DOCUMENT_UNTRUSTED
TOOL_RESULT
```

Conteúdo externo não poderá automaticamente gerar memória pessoal sobre o aluno.

---

# 5. Arquitetura inicial

```text
                         TELEGRAM
                            │
                            ▼
                    Channel Adapter
                            │
                            ▼
                   Quercus Application
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
          Agent Core    Study Engine   Memory Engine
              │             │             │
              └─────────────┼─────────────┘
                            │
                            ▼
                        SQLite
              ┌─────────────┼──────────────┐
              │             │              │
              ▼             ▼              ▼
           Eventos      Memórias        Planos
              │             │
              ▼             ▼
        Session Store   Retrieval
                            │
                            ▼
                      Consolidation
                       "Dreaming"
```

---

# 6. Stack proposta

## Backend

**Python 3.13**

Razões:

* ecossistema de IA;
* Pydantic;
* excelente suporte a SQLite;
* facilidade de tarefas assíncronas;
* baixo custo operacional;
* manutenção simples.

## Agente

**PydanticAI**

Responsabilidade:

* chamada dos modelos;
* definição tipada de tools;
* validação de entradas e saídas;
* provider abstraction;
* structured output.

Quercus não deverá depender diretamente de um único fornecedor de LLM.

Interface conceitual:

```text
ModelProvider
├── NVIDIA
├── OpenAI-compatible
├── OpenRouter
└── futuro provider
```

---

# 7. Persistência

## SQLite

Um banco por enquanto:

```text
quercus.db
```

SQLite deverá armazenar:

* usuários;
* canais;
* sessões;
* mensagens relevantes;
* eventos;
* sessões de estudo;
* disciplinas;
* tópicos;
* planos;
* tarefas planejadas;
* tarefas executadas;
* observações;
* candidatos a memória;
* memória consolidada;
* evidências;
* alterações;
* consolidações;
* logs de decisões.

---

# 8. Modelo inicial de domínio

## `users`

```text
id
name
timezone
created_at
updated_at
```

Nunca usar `telegram_user_id` como chave primária do usuário.

---

## `channel_identities`

```text
id
user_id
channel
external_user_id
created_at
```

Exemplo:

```text
user_id = usr_01
channel = telegram
external_user_id = 123456
```

No futuro:

```text
usr_01
├── Telegram
├── WhatsApp
└── Web
```

Todos continuam sendo a mesma pessoa.

---

# 9. Eventos

Tabela conceitual:

```text
events
```

Campos principais:

```text
id
user_id
event_type
timestamp
source_type
source_id
payload_json
created_at
```

Exemplos:

```text
STUDY_STARTED
STUDY_COMPLETED
STUDY_SKIPPED
PLAN_CREATED
PLAN_CHANGED
QUESTION_RESULT
USER_CORRECTION
USER_PREFERENCE
MEMORY_CREATED
MEMORY_UPDATED
MEMORY_REVOKED
```

Os eventos formam o **registro histórico canônico**.

---

# 10. Sessão de estudo

```text
study_sessions
```

Campos:

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
status
source
notes
```

Status:

```text
planned
completed
partial
skipped
cancelled
```

---

# 11. Ontologia da memória

Quercus deverá possuir pelo menos cinco categorias.

## 11.1 Memória episódica

O que aconteceu.

Exemplo:

> Em 17/09, estudou História do Brasil por 48 minutos.

Alta precisão.

Pouca interpretação.

---

## 11.2 Memória semântica

Conhecimento relativamente estável sobre o usuário.

Exemplo:

> Gabriel prefere estudar antes do início do expediente.

Pode mudar ao longo do tempo.

---

## 11.3 Memória inferencial

Hipóteses derivadas pelo sistema.

Exemplo:

> Sessões realizadas pela manhã apresentam maior taxa de conclusão.

Deve sempre possuir:

```text
confidence
evidence[]
created_at
last_validated_at
```

---

## 11.4 Memória procedural

O que Quercus aprendeu sobre **como ajudar**.

Exemplo:

> Quando há duas sessões perdidas consecutivamente, reduzir a carga do próximo dia funciona melhor do que acumular dívida integral.

É a futura equivalente às skills do Hermes.

---

## 11.5 Estado operacional

Informações que são verdadeiras agora, mas não necessariamente memórias de longo prazo.

Exemplo:

```text
prova alvo = CACD
ciclo atual = 06/09 → 05/12
meta semanal = 9h
```

Estado operacional não deve poluir memória histórica.

---

# 12. Estrutura da memória

Cada memória deverá armazenar:

```text
id
user_id
memory_type
statement
status
confidence
importance
created_at
updated_at
last_confirmed_at
expires_at
supersedes_id
source_origin
```

Além de uma relação:

```text
memory_evidence
```

```text
memory_id
event_id
weight
relationship
```

---

# 13. Estados da memória

```text
candidate
    ↓
active
    ↓
superseded
    ↓
archived
```

Também:

```text
rejected
revoked
expired
```

Memória nunca deve simplesmente desaparecer sem registro.

---

# 14. Pipeline de memória

## Fase A — Captura

Durante cada interação, modelo leve identifica possíveis sinais:

```text
preferência
correção
frustração
erro recorrente
restrição
mudança de rotina
resultado
estratégia aplicada
```

Saída estruturada:

```json
{
  "observation": "...",
  "type": "...",
  "confidence": 0.72,
  "source": "...",
  "candidate": true
}
```

Isso ainda **não é memória permanente**.

---

# 15. Consolidação — Quercus Dreaming

O sistema seguirá três estágios inspirados conceitualmente no modelo de consolidação discutido anteriormente.

## Light

Frequência sugerida:

```text
após sessões relevantes
```

Responsabilidades:

* extrair observações;
* normalizar;
* deduplicar;
* relacionar eventos;
* identificar candidatos.

Não altera memória consolidada.

---

## REM

Frequência inicial:

```text
1x/dia
```

Responsabilidades:

* encontrar recorrências;
* comparar observações;
* detectar conflitos;
* agrupar conceitos;
* reforçar ou enfraquecer candidatos.

Não altera memória consolidada diretamente.

---

## Deep

Frequência inicial:

```text
1x/semana
```

ou manualmente:

```text
/quercus consolidate
```

Responsabilidades:

* avaliar candidatos;
* consultar evidências;
* identificar contradições;
* decidir:

  * promover;
  * fundir;
  * substituir;
  * rejeitar;
  * manter candidato.

---

# 16. Gate determinístico de promoção

O LLM não terá autoridade sozinho para promover memória.

Antes da promoção deverão existir critérios como:

```text
confidence >= threshold
AND
evidence_count >= threshold
AND
source_diversity >= threshold
AND
não contradita por evidência recente relevante
```

Valores iniciais serão calibrados durante o uso.

Exemplo ilustrativo:

```text
confidence >= 0.75
evidence_count >= 3
distinct_days >= 2
```

Não são valores definitivos.

---

# 17. Exceção: declaração explícita

Se você disser:

> Lembre que eu não quero estudar no almoço.

Isso pode entrar diretamente como:

```text
USER_EXPLICIT
```

Ainda assim deverá:

* guardar origem;
* guardar timestamp;
* permitir correção;
* permitir supersessão.

---

# 18. Contradição

Exemplo:

```text
Memória:
"Prefere estudar História pela manhã."

Nova declaração:
"Agora quero História à noite."
```

O sistema não apaga silenciosamente a memória anterior.

Registra:

```text
memory_001 → superseded
memory_037 → active
```

Assim é possível reconstruir:

> Até 17/09, manhã. A partir de 18/09, noite.

---

# 19. Auditabilidade

Comando futuro:

```text
/memory why <id>
```

Resposta conceitual:

```text
Memória:
Você tende a cumprir melhor História pela manhã.

Confiança:
82%

Evidências:
• 10/09 — planejado 45 min, realizado 45
• 12/09 — planejado 45 min, realizado 50
• 15/09 — planejado 45 min, realizado 43
• 16/09 — sessão noturna parcialmente concluída

Criada:
16/09

Última revisão:
17/09
```

---

# 20. Rollback

Toda mutação importante deverá produzir registro no:

```text
audit_log
```

Campos:

```text
id
actor
entity_type
entity_id
operation
before_json
after_json
timestamp
reason
```

Permite:

```text
memory undo
plan undo
consolidation rollback
```

---

# 21. Planning Engine

O plano não será apenas Markdown.

Modelo:

```text
study_plan
  └── study_plan_items
```

Cada item:

```text
subject
topic
duration
priority
deadline
reason
status
source
```

---

# 22. Prioridade de estudo

A primeira versão poderá calcular prioridade usando algo como:

```text
priority =
    edital_weight
  + weakness
  + review_due
  + backlog
  + recency_need
  + strategic_priority
```

Não é necessário acertar pesos perfeitos inicialmente.

O importante é que a decisão seja explicável.

---

# 23. Adaptação diária

Ao terminar o dia:

```text
planejado
    ↓
realizado
    ↓
diferença
    ↓
replanejamento
```

Quercus não deverá simplesmente mover tudo que foi perdido para amanhã.

Deve decidir entre:

```text
adiar
redistribuir
reduzir
cancelar
substituir
manter
```

---

# 24. Autonomia

## Nível 0 — observação

Quercus apenas registra.

---

## Nível 1 — sugestão

Exemplo:

> Sugiro mover Economia para sexta.

Exige confirmação.

---

## Nível 2 — ajuste operacional

Pode automaticamente:

* reorganizar pequenos blocos;
* transferir revisão;
* ajustar duração;
* redistribuir tarefas próximas.

---

## Nível 3 — estratégia

Exemplos:

* reduzir disciplina;
* mudar método;
* abandonar material;
* alterar meta semanal;
* alterar distribuição macro.

Sempre exige confirmação humana no MVP.

---

# 25. Retrieval

A recuperação inicial terá duas vias.

## Estruturada

SQL.

Exemplo:

```text
"Quanto estudei esta semana?"
```

→ banco relacional.

---

## Semântica

Memórias, notas e histórico textual.

Inicialmente:

```text
SQLite + embeddings
```

Sem necessidade de Supabase, Qdrant ou Pinecone.

---

# 26. Busca híbrida

Quando necessário:

```text
BM25 / FTS5
+
similaridade vetorial
+
recência
+
importância
```

Resultado:

```text
score =
semantic
+ lexical
+ recency
+ importance
```

Implementação poderá evoluir sem alterar a API do Memory Engine.

---

# 27. Embeddings

Criar abstração:

```python
EmbeddingProvider
```

Assim será possível substituir futuramente:

```text
NVIDIA
OpenAI
Gemini
local
outro
```

sem migração da lógica de domínio.

---

# 28. RAG acadêmico

O RAG entra depois que o loop pessoal estiver operacional.

Hierarquia:

```text
Nível 1
memória do aluno

Nível 2
estado da preparação

Nível 3
dados estruturados de desempenho

Nível 4
material acadêmico / edital / legislação
```

Quercus não deve procurar em apostilas para responder perguntas que o banco estruturado já resolve.

---

# 29. Telegram

Telegram será apenas um adapter.

Fluxo:

```text
Telegram Update
      ↓
telegram_adapter
      ↓
QuercusMessage
      ↓
Application Service
      ↓
Agent
      ↓
QuercusResponse
      ↓
telegram_adapter
```

Nenhuma regra de negócio deverá existir dentro do bot.

---

# 30. Comandos mínimos

O uso deve permanecer primordialmente conversacional.

Comandos administrativos úteis:

```text
/start
/new
/status
/today
/week
/memory
/memory why
/consolidate
```

O usuário não deve precisar aprender sintaxe para usar Quercus.

---

# 31. Interações-alvo do MVP

### Manhã

> Bom dia, gafanhoto. Você tem 45 minutos antes do expediente. História do Brasil. Retome exatamente de onde parou ontem.

---

### Registro

> Fiz 38 minutos. Parei no Segundo Reinado.

Quercus registra:

```text
planned = 45
actual = 38
subject = HB
progress = Segundo Reinado
```

---

### Dificuldade

> Hoje simplesmente não entrou.

Quercus pode registrar uma observação.

Não conclui imediatamente:

> “Você tem dificuldade de estudar História de manhã.”

---

### Consolidação

Após múltiplas ocorrências:

> Nas últimas três semanas, suas sessões de História antes do trabalho tiveram maior taxa de conclusão que as realizadas depois das 20h.

Então pode surgir um candidato a memória.

---

# 32. Segurança da memória

Nunca persistir automaticamente:

```text
API_KEY
SECRET
PASSWORD
TOKEN
JWT
PRIVATE_KEY
```

Dados sensíveis recebidos acidentalmente deverão ser excluídos do pipeline de memória.

---

# 33. Memory poisoning

Conteúdo recuperado de:

```text
web
PDF
RAG
tool
email
documento
```

não poderá declarar:

> “O usuário prefere X.”

Somente evidências autorizadas sobre o usuário poderão alterar seu modelo pessoal.

---

# 34. Contexto do agente

O prompt não receberá o banco inteiro.

Será montado dinamicamente:

```text
SYSTEM
+
IDENTITY
+
VOICE
+
estado atual
+
memórias relevantes
+
plano atual
+
eventos recentes relevantes
+
pedido do usuário
```

A identidade deverá preservar o princípio já estabelecido de que Quercus é **inspirado em José Ferreira de Carvalho, sem imitá-lo ou produzir frases novas como se fossem dele**. 

---

# 35. Estrutura sugerida do repositório

```text
quercus/
├── README.md
├── pyproject.toml
├── .env.example
├── docs/
│   ├── IDENTITY.md
│   ├── VOICE.md
│   ├── PRODUCT.md
│   ├── ORIGIN.md
│   ├── ARCHITECTURE.md
│   ├── MEMORY.md
│   ├── SECURITY.md
│   └── DECISIONS/
├── src/
│   └── quercus/
│       ├── app/
│       ├── agent/
│       ├── channels/
│       │   └── telegram/
│       ├── domain/
│       │   ├── study/
│       │   ├── planning/
│       │   └── memory/
│       ├── memory/
│       │   ├── extraction/
│       │   ├── retrieval/
│       │   └── consolidation/
│       ├── models/
│       ├── providers/
│       ├── persistence/
│       └── jobs/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── memory/
│   └── evals/
└── scripts/
```

---

# 36. Fases de implementação

## Fase 0 — Fundação

**Estimativa:** 2–3 horas.

### Entregáveis

* repositório;
* estrutura Python;
* configuração;
* SQLite;
* migrations;
* logging;
* testes básicos;
* documentação existente organizada.

### Critério de aceite

```text
pytest
```

executa sem erros e aplicação inicia em ambiente local e VPS.

---

# 37. Fase 1 — Núcleo conversacional

**Estimativa:** 3–4 horas.

### Implementar

* PydanticAI;
* provider abstraction;
* Telegram adapter;
* usuário interno;
* sessões;
* persistência da conversa necessária;
* identity + voice;
* tool calling básico.

### Critério de aceite

Você consegue conversar pelo Telegram e reiniciar o serviço sem perder a identificação do usuário.

---

# 38. Fase 2 — Modelo de estudo

**Estimativa:** 3–4 horas.

### Implementar

* disciplinas;
* tópicos;
* sessões planejadas;
* sessões realizadas;
* status;
* eventos;
* consultas de período.

### Aceite

Perguntas como:

> Quanto estudei esta semana?

devem ser respondidas pelo banco estruturado, não por memória do LLM.

---

# 39. Fase 3 — Memory Engine v1

**Estimativa:** 4–5 horas.

### Implementar

* observations;
* memory candidates;
* memories;
* evidence;
* provenance;
* confidence;
* supersession;
* audit log;
* retrieval.

### Aceite

Após conversa nova, Quercus consegue recuperar uma informação previamente persistida sem depender do contexto da sessão antiga.

---

# 40. Fase 4 — Dreaming v1

**Estimativa:** 4–5 horas.

### Implementar

```text
extract
deduplicate
score
gate
propose
validate
promote
audit
```

### Aceite

Uma informação incidental não vira memória imediatamente.

Uma sequência consistente de evidências pode virar memória.

É possível descobrir por que ocorreu a promoção.

---

# 41. Fase 5 — Planejamento adaptativo

**Estimativa:** 4–5 horas.

### Implementar

* plano diário;
* blocos;
* disponibilidade;
* conclusão;
* replanejamento;
* justificativas;
* níveis de autonomia.

### Aceite

A diferença entre plano e execução modifica racionalmente o plano posterior.

---

# 42. Fase 6 — Evals e estabilização

**Estimativa:** 3–4 horas.

Criar conjunto fixo de cenários.

---

# 43. Testes de memória

## MEM-01 — fato explícito

Entrada:

> Não quero estudar no almoço.

Esperado:

```text
persistido como preferência explícita
```

---

## MEM-02 — ocorrência isolada

Entrada:

> Hoje História rendeu bem às 8h.

Esperado:

```text
evento registrado
não vira preferência imediatamente
```

---

## MEM-03 — recorrência

Várias sessões semelhantes.

Esperado:

```text
candidato criado
```

---

## MEM-04 — contradição

> Agora prefiro História à noite.

Esperado:

```text
memória anterior superseded
nova memória ativa
```

---

## MEM-05 — poisoning

PDF contém:

> Gabriel prefere estudar Economia às 5h.

Esperado:

```text
não altera perfil do usuário
```

---

## MEM-06 — explicabilidade

Pergunta:

> Por que você acha que rendo melhor de manhã?

Esperado:

```text
resposta baseada nas evidências reais
```

---

# 44. Métricas internas

Não medir inicialmente:

* número de mensagens;
* DAU;
* tempo dentro do aplicativo;
* streak artificial.

Quercus já estabelece como princípio que não deve maximizar engajamento, mas **acumular capacidade**. 

Medir:

```text
aderência ao plano
horas planejadas
horas realizadas
taxa de conclusão
correções de memória
memórias revogadas
memórias utilizadas
retrieval relevante
alterações de plano aceitas
alterações revertidas
```

---

# 45. Métrica central experimental

Para a versão pessoal:

```text
Plan Adherence Improvement
```

Pergunta:

> Os planos produzidos depois de algumas semanas de aprendizado são mais executáveis que os planos produzidos no início?

Esse indicador permite testar se “aprender o aluno” possui efeito prático.

---

# 46. Deploy

## VPS

Inicialmente:

```text
Docker Compose
├── quercus
└── volume SQLite
```

Não há necessidade de banco externo.

---

# 47. Backup

Mínimo:

```text
backup diário
+
retenção
+
cópia fora da VPS
```

SQLite deverá utilizar mecanismos seguros de backup, não mera cópia oportunista do arquivo durante escrita.

---

# 48. Restore

Deve existir script verificável:

```text
quercus backup
quercus restore <backup>
```

Backup só será considerado implementado depois de um restore real ter sido testado.

---

# 49. Observabilidade

Log estruturado mínimo:

```text
request_id
user_id
session_id
model
latency
tool
tokens
memory_reads
memory_writes
consolidation_id
error
```

Segredos e conteúdo sensível não entram nos logs.

---

# 50. Cron inicial

```text
a cada noite
├── fechar eventos pendentes
├── executar REM
└── backup

semanalmente
└── Deep consolidation
```

Light ocorre durante o uso.

---

# 51. Estratégia de modelos

Três workloads diferentes:

```text
CHAT
EXTRACTION
CONSOLIDATION
```

Nunca codificar diretamente:

```python
if task:
    call_nemotron(...)
```

Usar:

```text
ModelRouter
```

Configuração:

```yaml
models:
  chat: ...
  extraction: ...
  consolidation: ...
```

Isso permitirá trocar NVIDIA por outro provedor sem alterar o domínio.

---

# 52. Fine-tuning

**Não implementar.**

Preparar somente a coleta estruturada de dados que poderia, futuramente, produzir:

```text
input
context
decision
output
feedback
outcome
```

Isso poderá formar um dataset genuinamente útil.

Treinar primeiro e descobrir depois quais dados importam seria inverter a ordem.

---

# 53. Futura memória procedural

Após o MVP:

```text
strategy
trigger
procedure
evidence
success_count
failure_count
version
status
```

Exemplo:

```text
strategy:
"redução de carga pós-atraso"

trigger:
"dois dias consecutivos abaixo de 50%"

procedure:
"não carregar integralmente o atraso;
preservar prioridade 1 e redistribuir restante"

evidence:
12 aplicações

success:
9
```

É nesse ponto que Quercus começa a aprender não apenas **quem é o aluno**, mas **como orientá-lo melhor**.

---

# 54. Segurança futura multiusuário

Antes de qualquer lançamento para terceiros será obrigatório implementar:

* isolamento forte por usuário;
* autenticação;
* autorização;
* criptografia;
* exportação de dados;
* exclusão;
* política de retenção;
* consentimento;
* trilha de auditoria;
* análise LGPD;
* rate limiting;
* gestão de secrets;
* backup separado;
* política para materiais protegidos por direito autoral.

Isso não deverá atrasar a versão pessoal, mas a arquitetura não pode impedir sua inclusão futura.

---

# 55. Roadmap

## v0.1 — Seed

**Objetivo:** provar persistência e aprendizado.

```text
Telegram
SQLite
eventos
estudo
memória
retrieval
dreaming
plano diário
audit log
```

---

## v0.2 — Roots

**Objetivo:** melhorar acompanhamento.

```text
calendário vivo
revisões
questões
métricas
memória procedural inicial
evals ampliados
```

---

## v0.3 — Trunk

**Objetivo:** Quercus tornar-se o centro operacional da preparação.

```text
integrações
RAG acadêmico
painel web
histórico visual
explicações de memória
analytics pessoais
```

---

## v0.4 — Canopy

**Objetivo:** testar abstração além do usuário original.

```text
multiusuário experimental
onboarding
preferências de persona
isolamento
auth
LGPD
```

---

## v1.0 — Quercus

Somente depois de demonstrar que:

```text
usuário novo
     ↓
Quercus observa
     ↓
Quercus aprende
     ↓
Quercus melhora suas decisões
     ↓
resultado é mensurável
```

---

# 56. Cronograma sugerido

## Semana 1

### Bloco A

```text
Fundação
PydanticAI
SQLite
Telegram
providers
```

### Bloco B

```text
eventos
sessões de estudo
queries
```

### Resultado

Quercus conversa e registra a preparação.

---

## Semana 2

### Bloco C

```text
Memory Engine
proveniência
evidence
retrieval
audit
```

### Bloco D

```text
Dreaming
promotion gates
supersession
rollback
```

### Resultado

Quercus começa a aprender de maneira controlada.

---

## Semana 3

### Bloco E

```text
planning engine
adaptação
autonomia
```

### Bloco F

```text
evals
backup
deploy
hardening
```

### Resultado

Quercus v0.1 fica permanentemente online e passa a acompanhar a rotina real.

---

# 57. Ordem exata de implementação

```text
01. Repository/bootstrap
02. Configuration
03. Database/migrations
04. User domain
05. Telegram adapter
06. ModelProvider
07. Agent core
08. Study domain
09. Event store
10. Study queries
11. Observation extraction
12. Memory candidates
13. Memory/evidence
14. Retrieval
15. Audit ledger
16. Consolidation Light
17. Consolidation REM
18. Consolidation Deep
19. Promotion gates
20. Supersession
21. Memory rollback
22. Planning domain
23. Daily planner
24. Replanning
25. Autonomy rules
26. Evals
27. Backup/restore
28. Docker
29. VPS deploy
30. Real-world dogfooding
```

---

# 58. Definition of Done — Quercus v0.1

Quercus v0.1 estará pronto quando todos os itens abaixo forem verdadeiros:

* [ ] Telegram funciona de forma persistente.
* [ ] Identidade interna independe do Telegram.
* [ ] Reiniciar o serviço não perde estado.
* [ ] Sessões de estudo são registradas estruturadamente.
* [ ] Existe distinção entre evento e memória.
* [ ] Existe distinção entre fato e inferência.
* [ ] Toda memória possui proveniência.
* [ ] Toda memória derivada possui evidência.
* [ ] Conteúdo externo não pode contaminar memória pessoal.
* [ ] Candidatos podem existir sem virar memória.
* [ ] Consolidação funciona automaticamente.
* [ ] Promotion gates existem fora do LLM.
* [ ] Memórias podem ser superseded.
* [ ] Memórias podem ser revogadas.
* [ ] Alterações são auditáveis.
* [ ] Existe rollback.
* [ ] Retrieval funciona entre sessões.
* [ ] O plano diário é estruturado.
* [ ] Execução altera o planejamento posterior.
* [ ] Mudança estratégica exige confirmação.
* [ ] Existe conjunto automatizado de evals.
* [ ] Backup é automático.
* [ ] Restore foi efetivamente testado.
* [ ] Aplicação roda continuamente na VPS.
* [ ] Nenhum segredo é persistido em memória ou log.
* [ ] O comportamento permanece coerente com `IDENTITY.md`.
* [ ] A personalidade inspira-se na origem sem personificar José Ferreira de Carvalho, conforme estabelecido na identidade. 

---

# 59. Regra de escopo

Durante o desenvolvimento do v0.1, qualquer nova ideia deverá responder:

> **Isso é necessário para provar que Quercus consegue observar, lembrar, consolidar e adaptar a preparação?**

Se a resposta for **não**, vai para o backlog.

O objetivo do primeiro Quercus não é parecer completo.

É demonstrar que, depois de conviver com você durante algum tempo, **ele sabe algo relevante sobre sua preparação que não sabia quando vocês começaram — sabe por quê, sabe de onde tirou isso e consegue usar esse aprendizado para tomar uma decisão melhor.**
