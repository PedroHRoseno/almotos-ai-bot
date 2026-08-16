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
| `WHATSAPP_VERIFY_TOKEN` | Sim | Token de verificação do webhook (Meta) |
| `WHATSAPP_ACCESS_TOKEN` | Sim | Token da Meta Cloud API |
| `WHATSAPP_PHONE_NUMBER_ID` | Sim | ID do número WhatsApp Business |
| `WHATSAPP_APP_SECRET` | Sim (prod) | App Secret; sem isso o POST `/webhook` retorna 403 |
| `WHATSAPP_API_VERSION` | Não | Padrão: `v21.0` |

**Remover** se ainda existirem: `OPENAI_API_KEY`, `VEHICLES_API_URL`, `VEHICLES_API_TOKEN`. O bot **não** chama LLM nem o Kotlin (ADR-003).

`PORT` é injetado pelo Railway.

## 3. Domínio e webhook Meta

- **Generate Domain** → `https://seu-bot.up.railway.app`
- Callback URL: `https://seu-bot.up.railway.app/webhook`
- Verify token = `WHATSAPP_VERIFY_TOKEN`
- Assinar o campo **messages**

## 4. Health

```bash
curl https://seu-bot.up.railway.app/health
# {"status":"ok"}
```
