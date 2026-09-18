# Benchmark Arquitetural: Melhores Práticas de Memória e Telegram (Hermes Agent & OpenCLAW)

**Data da pesquisa:** 18 de setembro de 2026  
**Fontes primárias:**
- **Hermes Agent (Nous Research):** [github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — [Persistent Memory Docs](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/memory.md), [Telegram Integration Docs](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/messaging/telegram.md), [Creative Dream Loop](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/skills/optional/creative/creative-dream-loop.md).
- **OpenCLAW (OpenClaw Foundation):** [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw) — [Architecture Docs](https://docs.openclaw.ai/concepts/architecture), [Memory System Docs](https://docs.openclaw.ai/concepts/memory), [Telegram Channel Docs](https://docs.openclaw.ai/channels/telegram).

---

## 1. Mapeamento dos Paradigmas de Memória

### 1.1 Hermes Agent: O Padrão "Frozen Snapshot" e Limites Rígidos
No Hermes Agent, a memória permanente é deliberadamente minimalista e concisa:
1. **Dois arquivos canônicos:**
   - `USER.md` (~1.375 caracteres / ~500 tokens): perfil do usuário, estilo de comunicação, preferências estritas.
   - `MEMORY.md` (~2.200 caracteres / ~800 tokens): notas do agente, fatos de ambiente, lições aprendidas.
2. **Frozen Snapshot Pattern:**
   - Na inicialização de cada sessão, o conteúdo de memória é injetado estaticamente no system prompt.
   - Ele **permanece congelado durante toda a sessão**, preservando o *prefix caching* do LLM (redução drástica de latência e custo).
   - Mutações feitas durante a conversa são persistidas imediatamente em disco, mas só entram no prompt na sessão seguinte.
3. **Limites de Capacidade & Compactação Orientada a Erro:**
   - O sistema **não** faz compactação silenciosa nem truncamento cego. Quando a memória excede a cota, a ferramenta `memory` retorna um erro explicitando a taxa de uso e a lista de entradas existentes, instruindo o agente a fundir (`replace`) ou podar (`remove`) entradas redundantes no mesmo turno antes de retentar o `add`.
4. **Substituição por Substring Única:**
   - Para alterar ou revogar memórias, a ferramenta usa casamento de substring unívoco (`old_text`), evitando que o modelo tenha que transcrever hashes ou textos longos completos.
5. **Ciclo de Consolidação (Dreaming):**
   - **Fase Light:** Varredura em sessões recentes gerando candidatos provisórios sem alterar o store consolidado.
   - **Fase Deep:** Avaliação multicritério (novidade, durabilidade, especificidade e concisão) para promover candidatos.
   - **Fase REM:** Identificação de padrões recorrentes entre sonhos anteriores e aprendizado procedural.
   - **Auditabilidade / Diário de Sonhos (`DREAMS.md`):** Todo o histórico de promoções, fusões e descartes é registrado de forma transparente.

### 1.2 OpenCLAW: Arquitetura em Camadas e Indexação Híbrida
O OpenCLAW organiza o fluxo de persistência em três camadas sucessivas:
1. **Camada 1 (Transcrições de Sessão):** Arquivos JSONL com o histórico bruto da conversa.
2. **Camada 2 (Notas Diárias / Event Log):** Arquivos `memory/YYYY-MM-DD.md` estruturados como log append-only dos eventos ocorridos em cada dia.
3. **Camada 3 (Memória Permanente):** Arquivo consolidado `MEMORY.md` mantendo o conhecimento de longo prazo.
4. **Indexação Local em SQLite com Busca Híbrida:**
   - O `memory-core` segmenta os arquivos Markdown em chunks (ex.: 400 tokens com overlap de 80 tokens).
   - Indexa os chunks em SQLite local via BM25/FTS5 combinado com embeddings vetoriais.
   - Elimina qualquer dependência de estado oculto em nuvem (*No Hidden State*): tudo o que o agente sabe existe como Markdown/SQLite auditável no disco.
5. **Comando Canônico de Promoção (`openclaw memory promote`):**
   - Permite ranquear os candidatos de curto prazo e consolidar itens de alta relevância para a memória definitiva.

---

## 2. Mapeamento da Integração com Telegram

### 2.1 Hermes Agent: Gateway Desacoplado, Ciclo de Vida e Mídia
1. **Desacoplamento Rigoroso (Gateway Adapter):**
   - O bot roda via `python-telegram-bot` em processo de gateway, convertendo mensagens para o barramento interno. O core do agente não sabe que está falando no Telegram.
2. **Segurança Fail-Closed (`TELEGRAM_ALLOWED_USERS`):**
   - IDs numéricos do Telegram são validados antes de qualquer execução. Usuários fora da allowlist são silenciosamente ignorados ou bloqueados.
3. **Fronteira de Sessão Explícita (`/new`):**
   - Chats de mensageiros são contínuos por natureza. Sem cortes, o contexto do LLM infla e o snapshot congelado de memória nunca atualiza. O comando `/new` encerra a sessão ativa, descarrega o contexto efêmero e recarrega os arquivos de memória atualizados no próximo system prompt.
4. **Protocolo de Envio de Arquivos (`MEDIA:`):**
   - O modelo apenas emite no texto a tag `MEDIA:/caminho/do/arquivo.pdf` (ou `.png`, `.ogg`, `.txt`). O gateway intercepta essa tag e realiza o upload nativo pela Bot API, desacoplando o modelo de chamadas diretas de upload.
5. **Áudio e Mensagens de Voz:**
   - Áudios recebidos podem ser transcritos automaticamente via Whisper (local ou API) ou repassados como caminho `.ogg` local no sistema de arquivos para processamento pelo agente.
   - Áudios de resposta são emitidos como bolhas nativas de voz (`voice`) via conversão ffmpeg para Opus.
6. **Flexibilidade Long-Polling vs. Webhook:**
   - Long-polling para desenvolvimento local e servidores VPS simples (sem portas públicas abertas).
   - Webhook com validação de assinatura `TELEGRAM_WEBHOOK_SECRET` para ambientes serverless ou cloud com auto-wake (Fly.io, Railway).

### 2.2 OpenCLAW: Tópicos como Contextos e Observação Passiva
1. **Isolamento por Tópicos do Telegram (Forum Mode):**
   - O suporte a fóruns/tópicos permite associar cada tópico a uma sessão/contexto isolado (ex.: um tópico para "História do Brasil", outro para "Política Internacional").
2. **Observação Passiva de Mensagens (`observe_unmentioned_group_messages`):**
   - O bot escuta mensagens do grupo sem responder ativamente, registrando o histórico como contexto prévio passivo.
   - Quando é mencionado (`@bot`), ele usa as mensagens anteriores como contexto factual com tags `[nickname|user_id]`.
3. **Pareamento de Novos Contatos (`pairing`):**
   - Mensagens diretas de usuários desconhecidos exigem aprovação via código de pareamento (`openclaw pairing approve`), protegendo a VPS de acessos indevidos.

---

## 3. O que Quercus Deve Copiar, Adaptar e Evitar

| Recurso / Prática | Como Hermes / OpenCLAW Fazem | Recomendação para o Quercus | Por quê? |
|---|---|---|---|
| **Formato de Memória** | Markdown de texto livre (`MEMORY.md`, `USER.md`). | **ADAPTAR**: Híbrido (tabelas relacionais estruturadas no SQLite + Markdown destilado). | Quercus precisa de métricas analíticas exatas de estudo (`planned_minutes`, `actual_minutes`, `taxa_conclusão`) que não podem depender de inferência imprecisa de texto, mas precisa de enunciados semânticos para preferências e estilo de estudo. |
| **Snapshot Congelado** | Injeta memória no system prompt no início da sessão e não altera mid-turn (Hermes). | **COPIAR DIRETAMENTE**: Montar o system prompt com as memórias ativas no início da sessão e manter fixo. | Preserva o *prefix cache* do modelo, barateia tokens e evita inconsistências durante a mesma rodada de conversa. |
| **Fronteira de Sessão** | Comando `/new` e cortes diários (Hermes). | **COPIAR DIRETAMENTE**: Implementar `/new` no Telegram e corte automático de sessão às 04:00 da manhã. | No Telegram, conversas nunca "fecham". Um corte diário garante que o planejamento do novo dia abra com a memória consolidada na noite anterior pelo REM dreaming. |
| **Promoção de Memória** | O próprio LLM decide quando salvar via tool call `memory(action="add")` (Hermes). | **EVITAR / INOVAR**: O LLM **não** promove sozinho. Exigir o Gate Determinístico de Promoção (`confidence`, `evidence_count`, `source_diversity`). | Evita *hallucination poisoning* e atende à regra de ouro do Quercus: "aconteceu ≠ foi observado ≠ padrão ≠ memória". Uma única sessão boa de manhã não é preferência matutina definitiva. |
| **Rastreabilidade de Evidências** | Log de texto em diário de sonhos `DREAMS.md` (Hermes/OpenCLAW). | **COPIAR E FORTALECER**: Tabela relacional `memory_evidence (memory_id, event_id, weight)`. | Permite responder de forma exata e pericial à pergunta: *"Por que você acha isso sobre mim?"*, recuperando os eventos brutos exatos que geraram a inferência. |
| **Protocolo de Mídia no Telegram** | Marcação `MEDIA:/path/to/file` no texto da resposta, interceptada pelo gateway (Hermes). | **COPIAR DIRETAMENTE**: O agente emite `MEDIA:/caminho/do/plano.pdf` ou áudio, e o adaptador do Telegram despacha como anexo nativo. | Desacopla 100% a lógica de negócio do agente das APIs da plataforma Telegram. |
| **Segurança e Acesso** | `TELEGRAM_ALLOWED_USERS` com IDs numéricos (Hermes) e pareamento (OpenCLAW). | **COPIAR DIRETAMENTE**: Restringir o bot por ID numérico do usuário (Gabriel) no `.env`. | Protege o bot pessoal de qualquer terceiro no Telegram sem necessidade de autenticação complexa na VPS. |
| **Observabilidade e Diário de Sonhos** | `DREAMS.md` para auditoria humana do que foi aprendido e esquecido. | **COPIAR**: Gerar um sumário de consolidação que pode ser enviado pelo Telegram após o ciclo semanal de Deep consolidation. | O usuário revisa e pode emitir correções imediatas caso o Quercus tenha consolidado uma hipótese errada. |
