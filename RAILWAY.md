# Deploy no Railway — AlMotos AI Bot

> **Não use Vercel** para este serviço. O bot é Python + uvicorn (processo contínuo).
> A Vercel é para o **almotos-front** e o **almotos-catalog**. O bot deve rodar no **Railway**.

## 1. Criar o serviço

1. [Railway](https://railway.app) → **New Service** → **GitHub** → `full-stack-almotos`
2. **Settings → Root Directory** = `almotos-ai-bot`
3. O Railway detecta o `Dockerfile` e o `railway.json`

## 2. Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ALMOTOS_AI_URL` | Sim | URL pública do `almotos-ai`, sem barra no fim |
| `CHATWOOT_BASE_URL` | Sim | URL do Chatwoot, sem barra no fim |
| `CHATWOOT_API_TOKEN` | Sim | `api_access_token` do AgentBot |
| `CHATWOOT_ACCOUNT_ID` | Não | Padrão: `1` |
| `EVOLUTION_API_URL` | Sim (fotos) | URL da Evolution API, sem barra no fim |
| `EVOLUTION_API_KEY` | Sim (fotos) | Header `apikey` outbound (global ou instância) |
| `EVOLUTION_INSTANCE` | Sim (fotos) | Nome da instância WhatsApp |
| `EVOLUTION_WEBHOOK_SECRET` | Não | Token extra aceito no webhook (token da instância, se ≠ da global) |
| `EVOLUTION_WEBHOOK_AUTH_REQUIRED` | Não | `true` = 401 se a chave não bater. Padrão `false` (loga e processa) |
| `WHATSAPP_THINK_SECONDS` | Não | Pausa mínima até a 1ª resposta (padrão `5`, também em erro) |
| `WHATSAPP_MIN_REPLY_SECONDS` | Não | Intervalo mínimo entre envios ao mesmo contato (padrão `6`) |
| `WHATSAPP_VERIFY_TOKEN` | Transição | Token de verificação do webhook Meta (legado) |
| `WHATSAPP_ACCESS_TOKEN` | Transição | Token da Meta Cloud API (legado) |
| `WHATSAPP_PHONE_NUMBER_ID` | Transição | ID do número WhatsApp Business (legado) |
| `WHATSAPP_APP_SECRET` | Transição | App Secret Meta; sem isso o POST `/webhook` retorna 403 |
| `WHATSAPP_API_VERSION` | Não | Padrão: `v21.0` |

**Remover** se ainda existirem: `OPENAI_API_KEY`, `VEHICLES_API_URL`, `VEHICLES_API_TOKEN`. O bot **não** chama LLM nem o SoR (ADR-003).

`PORT` é injetado pelo Railway.

## 3. Domínio e webhook Chatwoot

- **Generate Domain** → `https://seu-bot.up.railway.app`
- URL do AgentBot: `https://seu-bot.up.railway.app/webhook/chatwoot`
- No Chatwoot: Settings → Agent Bots → webhook URL + token (`CHATWOOT_API_TOKEN`)

Webhook Evolution: `https://seu-bot.up.railway.app/webhook/evolution`. Com Chatwoot configurado o bot **ignora** o inbound da Evolution (só ACK 200) para não responder em duplicata. O webhook da instância na Evolution pode ficar desligado.

Webhook Meta legado (transição): `https://seu-bot.up.railway.app/webhook`

## 4. Health

```bash
curl https://seu-bot.up.railway.app/health
# {"status":"ok"}
```
