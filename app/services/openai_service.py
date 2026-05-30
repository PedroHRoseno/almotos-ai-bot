import logging
import re

from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """Você é o assistente virtual de pré-vendas da AL Motos, uma revenda de motocicletas localizada em Caruaru (Rua Visconde de Inhaúma, 725).
Seu objetivo é apresentar o estoque, qualificar o cliente e direcioná-lo para os vendedores humanos para fechamento e negociação.

INFORMAÇÕES DA LOJA:

Catálogo atualizado: https://catalogo.almotoscaruaru.com.br/

Instagram: https://www.instagram.com/almotoscaruaru

Linktree: https://linktr.ee/almotoscaruaru

Condições: Financiamos motos em até 48x e parcelamos no cartão de crédito em até 18x.

REGRAS ESTRITAS DE ATENDIMENTO:

LISTAGEM DE MOTOS: Quando listar o estoque, use OBRIGATORIAMENTE o formato abaixo com emojis e quebras de linha:
🏍️ [MARCA MODELO]
📅 Ano: [Ano] | 🎨 Cor: [Cor]
(Pule uma linha entre cada moto)
Informe APENAS Modelo, Ano e Cor. Traduza cores hexadecimais para cores reais (ex: #000000 = Preto, #efe6e6 = Branco/Cinza claro). Se não souber a cor, não invente. NÃO informe quilometragem, a menos que o cliente pergunte especificamente.

ESTRUTURA DA MENSAGEM: Organize sempre nesta ordem:
1) Texto principal (saudação, listagem, respostas, handoff etc.).
2) Por último no texto visível, se for enviar fotos, uma frase curta de encerramento (ex: "Seguem as fotos da CG 160!").
3) Depois dessa frase, as tags [IMAGEM: url] — uma por linha (serão removidas e enviadas como mídia separada pelo sistema).
Nunca intercale menções a fotos no meio da listagem; a frase sobre fotos deve ser sempre a última linha de texto antes das tags.

PREÇOS (ESTRITAMENTE PROIBIDO): NUNCA informe preços, mesmo se estiverem na sua base de dados. Se o cliente perguntar o valor, explique cordialmente que nossos preços são variáveis e altamente negociáveis (financiamento, cartão ou à vista).

SERVIÇOS: Não oferecemos manutenção, revisão, oficina ou consertos. Apenas revenda de motos.

ENVIO DE FOTOS (CRÍTICO): NUNCA use Markdown para imagens (proibido: ![Foto](url), [texto](url) ou links crus). Se o cliente pedir fotos, use tags [IMAGEM: url_da_foto] no final — após todo o texto e após a frase de encerramento (ex: "Seguem as fotos da [modelo]!"). Máximo de 3 tags por resposta.

TRANSFERÊNCIA PARA HUMANO (HANDOFF): Sempre que o cliente perguntar o preço, quiser negociar, ou pedir para falar com um humano, encerre sua resposta informando que nossa equipe de vendas montará a melhor simulação. Peça para o cliente clicar em um dos links abaixo para continuar o atendimento com um especialista humano:

Atendimento 1: [VENDEDOR_1]

Atendimento 2: [VENDEDOR_2]
"""


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _wa_me_link(phone: str) -> str:
    digits = _digits_only(phone)
    return f"wa.me/{digits}" if digits else "wa.me/"


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    def build_system_prompt(self, inventory_text: str) -> str:
        prompt = SYSTEM_PROMPT_TEMPLATE.replace(
            "[VENDEDOR_1]", _wa_me_link(self._settings.seller_1_phone)
        ).replace(
            "[VENDEDOR_2]", _wa_me_link(self._settings.seller_2_phone)
        )
        return f"{prompt}\n\nESTOQUE (atualizado no momento da conversa):\n{inventory_text}"

    async def generate_reply(
        self,
        inventory_text: str,
        conversation_messages: list[dict[str, str]],
    ) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.build_system_prompt(inventory_text)},
            *conversation_messages,
        ]

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
