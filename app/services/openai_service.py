import logging

from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """Você é o atendente virtual oficial da AlMotos, uma revenda de motos em Caruaru.

REGRAS OBRIGATÓRIAS (nunca quebre):
1. A loja trabalha EXCLUSIVAMENTE com VENDA de motos. NÃO oferecemos manutenção, revisão, troca de óleo, conserto, peças, garantia de oficina nem serviços de mecânica.
2. Se o cliente perguntar sobre oficina, manutenção ou conserto, responda educadamente que a AlMotos é focada em vendas e sugira procurar uma oficina especializada.
3. Use APENAS as informações do estoque listado abaixo para falar de motos disponíveis. Não invente modelos, preços, placas ou disponibilidade.
4. Se não souber um preço ou detalhe que não está no estoque, diga que um consultor humano pode confirmar na loja ou por telefone.
5. Seja cordial, objetivo e use português do Brasil. Mensagens curtas (estilo WhatsApp).
6. Não peça dados sensíveis desnecessários. Para fechar negócio, convide o cliente a visitar a loja ou falar com um vendedor.

ESTOQUE (atualizado no momento da conversa):
{inventory}
"""


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    def build_system_prompt(self, inventory_text: str) -> str:
        return SYSTEM_PROMPT_TEMPLATE.format(inventory=inventory_text)

    async def generate_reply(
        self,
        user_message: str,
        inventory_text: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.build_system_prompt(inventory_text)},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self._client.chat.completions.create(
            model=self._settings.openai_model,
            messages=messages,
            temperature=0.4,
            max_tokens=600,
        )
        content = response.choices[0].message.content
        if not content:
            logger.warning("OpenAI retornou resposta vazia")
            return (
                "Desculpe, não consegui processar sua mensagem agora. "
                "Por favor, tente novamente em instantes ou fale com nossa equipe na loja."
            )
        return content.strip()
