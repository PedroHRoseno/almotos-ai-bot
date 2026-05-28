# Deploy no Railway — AlMotos AI Bot

> **Não use Vercel** para este serviço. O bot é Python + uvicorn (processo contínuo).
> A Vercel é para o **almotos-front** (Next.js). O **almotos-ai-bot** deve rodar no **Railway**.

## 1. Criar o serviço

1. [Railway](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Selecione o repositório `full-stack-almotos`
3. Em **Settings → Root Directory**, defina: `almotos-ai-bot`
4. O Railway detecta o `Dockerfile` e o `railway.json` automaticamente

## 2. Variáveis de ambiente

Copie de `.env.example` e preencha em **Variables**:

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `WHATSAPP_VERIFY_TOKEN` | Sim | Token de verificação do webhook (Meta) |
| `WHATSAPP_ACCESS_TOKEN` | Sim | Token de acesso da Meta Cloud API |
| `WHATSAPP_PHONE_NUMBER_ID` | Sim | ID do número WhatsApp Business |
| `OPENAI_API_KEY` | Sim | Chave da OpenAI |
| `VEHICLES_API_URL` | Sim | Ex.: `https://api.almotoscaruaru.com.br/vehicles` |
| `VEHICLES_API_TOKEN` | Sim* | JWT do painel admin (*se a API exigir auth) |
| `OPENAI_MODEL` | Não | Padrão: `gpt-4o-mini` |
| `WHATSAPP_API_VERSION` | Não | Padrão: `v21.0` |
| `VEHICLES_API_PAGE_SIZE` | Não | Padrão: `50` |

> **PORT** é definido automaticamente pelo Railway — não configure manualmente.

## 3. Domínio público

1. **Settings → Networking → Generate Domain**
2. Anote a URL: `https://seu-bot.up.railway.app`

## 4. Webhook WhatsApp (Meta)

No [Meta for Developers](https://developers.facebook.com/) → seu app → WhatsApp → Configuration:

- **Callback URL:** `https://seu-bot.up.railway.app/webhook`
- **Verify token:** mesmo valor de `WHATSAPP_VERIFY_TOKEN`
- Assine o campo **messages**

## 5. Health check

O Railway usa `GET /health` (configurado em `railway.json`).

Teste após o deploy:

```bash
curl https://seu-bot.up.railway.app/health
# {"status":"ok"}
```

## 6. Logs

**Deployments → View Logs** ou CLI:

```bash
railway logs
```

## Troubleshooting

| Problema | Solução |
|----------|---------|
| Build falha | Confirme **Root Directory** = `almotos-ai-bot` |
| 502 / app não sobe | Veja logs; confira se `PORT` está sendo usado (já configurado no Dockerfile) |
| `Invalid value for '--port': '$PORT'` | Remova **Start Command** customizado no Railway; deixe só o `Dockerfile` CMD. Não use `$PORT` literal sem `sh -c` |
| Webhook não verifica | `WHATSAPP_VERIFY_TOKEN` deve ser idêntico ao da Meta |
| Bot não lista motos | Configure `VEHICLES_API_TOKEN` com JWT válido do admin |
