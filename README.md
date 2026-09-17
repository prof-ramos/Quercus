# Quercus

> O agente de preparação que cresce com você.  
> Um carro-escola na nuvem.

Quercus é um agente pessoal de preparação para concursos públicos, desenvolvido inicialmente para acompanhar uma única preparação real ao longo do tempo.

O primeiro usuário é também quem está construindo e testando o sistema.

O objetivo não é criar um cursinho, um chatbot sobre edital ou um banco de questões. O objetivo é descobrir se um agente com memória persistente consegue aprender, ao longo de meses de uso, como uma pessoa estuda e utilizar esse aprendizado para ajudá-la a se preparar melhor.

O primeiro campo de teste é o **CACD**.

---

## Ideia central

Quercus não sabe apenas sobre concursos.

**Ele aprende o concurseiro.**

O sistema acompanha o ciclo real da preparação:

```text
planejamento
     ↓
execução
     ↓
observação
     ↓
memória
     ↓
consolidação
     ↓
adaptação
     └────────→ próximo planejamento
```

A hipótese é simples:

> um agente que conhece o histórico real do aluno deve conseguir tomar decisões melhores depois de algumas semanas ou meses de convivência do que no primeiro dia.

Essa hipótese precisa ser demonstrada pelo uso real.

---

## O que Quercus faz

Na primeira versão, Quercus deve ser capaz de:

* conversar comigo sobre a preparação;
* conhecer meu plano atual;
* registrar o que foi planejado;
* registrar o que realmente aconteceu;
* acompanhar sessões de estudo;
* lembrar decisões e preferências relevantes;
* identificar possíveis padrões ao longo do tempo;
* consolidar apenas padrões suficientemente sustentados;
* recuperar memórias relevantes em conversas futuras;
* utilizar essas memórias ao sugerir novos planos;
* explicar por que acredita em determinada memória ou recomendação;
* permitir correção quando tiver aprendido algo errado.

---

## O que Quercus não é

Quercus não é:

* um cursinho;
* um professor artificial;
* um banco de questões;
* um chatbot com RAG sobre o edital;
* um substituto para materiais de estudo;
* um produto SaaS neste momento;
* uma plataforma multiusuário;
* um experimento de fine-tuning.

Conteúdo acadêmico poderá ser integrado quando for útil, mas não é o centro do projeto.

O núcleo é a relação entre:

**planejamento + execução + memória + adaptação**.

---

## Estado atual

**Fase:** protótipo pessoal / dogfooding.

O projeto está sendo construído para uso próprio.

Não há atualmente compromisso com:

* lançamento público;
* usuários externos;
* monetização;
* compatibilidade multiusuário;
* suporte;
* SLA;
* aplicativo mobile;
* WhatsApp;
* infraestrutura comercial.

Caso o sistema se mostre realmente útil durante uma preparação longa, uma versão destinada a terceiros poderá ser estudada posteriormente.

Essa possibilidade não é requisito da arquitetura atual.

---

## Primeiro cenário

A primeira rotina que Quercus precisa acompanhar é uma preparação real para o **Concurso de Admissão à Carreira de Diplomata — CACD**.

Exemplo:

```text
08:30

Quercus:
Hoje você tem 45 minutos antes do expediente.
História do Brasil. Retome de onde parou ontem.

...

Usuário:
Fiz 38 minutos. Parei no Segundo Reinado.

Quercus:
Registrado.
```

Essa interação aparentemente simples gera dados estruturados:

```text
disciplina: História do Brasil
planejado: 45 min
realizado: 38 min
progresso: Segundo Reinado
data: ...
```

Uma ocorrência isolada não deve produzir conclusões sobre o aluno.

Com o passar do tempo, várias ocorrências podem formar evidências para hipóteses como:

```text
sessões de História realizadas pela manhã
apresentam maior taxa de conclusão
```

A hipótese pode então tornar-se candidata a memória.

Somente depois de validação suficiente deverá ser tratada como conhecimento persistente.

---

## Memória

Quercus diferencia pelo menos quatro coisas:

```text
aconteceu
     ↓
foi observado
     ↓
pode existir um padrão
     ↓
há evidência suficiente para lembrar
```

Portanto:

```text
evento ≠ inferência ≠ memória
```

Exemplo:

### Evento

> Estudei História às 8h e rendeu bem.

### Inferência prematura

> Estudo História melhor pela manhã.

A segunda afirmação não deve ser armazenada automaticamente como verdade.

Quercus deve acumular evidências antes de promovê-la.

---

## Tipos de memória

### Episódica

O que aconteceu.

```text
Em 17/09 foram realizados 38 minutos de História do Brasil.
```

### Semântica

Informações relativamente estáveis.

```text
O usuário prefere estudar antes do início do expediente.
```

### Inferencial

Padrões identificados pelo sistema.

```text
Sessões realizadas pela manhã apresentam maior taxa de conclusão.
```

Inferências precisam manter as evidências que lhes deram origem.

### Procedural

O que Quercus aprende sobre como ajudar.

```text
Quando dois dias consecutivos ficam muito abaixo da meta,
redistribuir a carga funciona melhor do que carregar integralmente
o atraso para o dia seguinte.
```

Essa camada será desenvolvida apenas depois que o mecanismo básico de memória estiver funcionando bem.

---

## Consolidação

Quercus não transforma toda conversa em memória permanente.

Durante o uso ele coleta observações.

Periodicamente, um processo de consolidação deverá:

1. reunir observações recentes;
2. eliminar duplicações;
3. identificar recorrências;
4. procurar contradições;
5. avaliar evidências;
6. criar ou reforçar candidatos;
8. substituir memórias que deixaram de representar a situação atual.

Esse processo é provisoriamente chamado de **Dreaming**.

Ele é inspirado em mecanismos de consolidação encontrados em outros agentes, mas será implementado de forma muito menor e adequada ao problema do Quercus.

---

## Princípio de auditabilidade

Quercus deve conseguir responder:

> Por que você acha isso sobre mim?

Uma memória derivada não deve existir sem origem identificável.

Exemplo:

```text
Memória

"História tende a funcionar melhor pela manhã."

Evidências

10/09 — 45 planejados / 45 realizados
12/09 — 45 planejados / 50 realizados
15/09 — 45 planejados / 43 realizados
16/09 — sessão noturna parcialmente concluída
```

Se a conclusão estiver errada, ela precisa poder ser corrigida.

---

## Arquitetura inicial

A primeira arquitetura deverá permanecer pequena.

```text
Telegram
    │
    ▼
Quercus
    │
    ├── Agent
    ├── Study
    ├── Planning
    └── Memory
          │
          ▼
        SQLite
```

### Canal

Inicialmente:

**Telegram**

Telegram é apenas a interface de conversa.

A lógica do Quercus não deve depender dele.

### Backend

Inicialmente:

**Python**

### Agente

Previsto:

**PydanticAI**

### Persistência

Inicialmente:

**SQLite**

O objetivo é manter toda a aplicação simples o suficiente para rodar confortavelmente em uma VPS pequena.

---

## Modelos

Quercus não possui modelo próprio.

Os modelos são componentes substituíveis.

Inicialmente poderão existir workloads diferentes para:

```text
chat
extração
consolidação
```

O sistema deverá permitir trocar os modelos sem perder:

* histórico;
* memória;
* métricas;
* planejamento;
* conhecimento adquirido sobre o usuário.

A inteligência acumulada do Quercus deve permanecer principalmente **nos dados e no sistema de memória**, e não nos pesos de um modelo específico.

---

## Fine-tuning

Não faz parte da primeira versão.

Se algum dia houver material suficiente para justificar fine-tuning, ele deverá surgir de dados produzidos pelo uso real:

```text
contexto
→ decisão
→ resposta
→ feedback
→ resultado
```

Primeiro é preciso descobrir o que realmente funciona.

Depois se avalia se existe algo que valha a pena treinar.

---

## Estrutura do projeto

```text
quercus/
├── README.md
├── pyproject.toml
├── docs/
│   ├── IDENTITY.md
│   ├── VOICE.md
│   ├── PRODUCT.md
│   ├── ORIGIN.md
│   ├── ARCHITECTURE.md
│   └── MEMORY.md
├── src/
│   └── quercus/
│       ├── agent/
│       ├── channels/
│       ├── domain/
│       ├── memory/
│       ├── persistence/
│       └── providers/
├── migrations/
└── tests/
```

A estrutura poderá crescer conforme necessidades reais aparecerem.

Não serão criados módulos antecipadamente apenas porque poderiam ser úteis em uma eventual versão comercial.

---

## Desenvolvimento

A prioridade inicial é provar um único ciclo:

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

Enquanto esse ciclo não estiver funcionando, funcionalidades adicionais são secundárias.

---

## Critério de sucesso

Quercus terá cumprido seu primeiro objetivo quando, depois de algum tempo acompanhando uma preparação real:

1. souber coisas relevantes que não sabia no início;
2. essas coisas estiverem sustentadas por evidências;
3. conseguir recuperá-las quando forem pertinentes;
4. utilizá-las para alterar uma decisão futura;
5. conseguir explicar por que tomou essa decisão;
6. aceitar correção quando sua conclusão estiver errada.

Não basta parecer que lembra.

O aprendizado precisa produzir **efeito observável na preparação**.

---

## Identidade

**Quercus** significa carvalho em latim.

O projeto é inspirado em José Ferreira de Carvalho, sem pretender imitá-lo.

A identidade completa está documentada em:

```text
docs/IDENTITY.md
```

A voz:

```text
docs/VOICE.md
```

A origem:

```text
docs/ORIGIN.md
```

---

## Princípio

> Crescimento composto, não viral.

Quercus não existe para maximizar mensagens, sessões ou tempo dentro de um aplicativo.

Ele existe para acumular capacidade.

---

**Quercus**
O agente de preparação que cresce com você.
*Um carro-escola na nuvem.*