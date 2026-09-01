import re

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
_MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)")
_IMAGE_TAG = re.compile(r"\[IMAGEM:\s*(https?://[^\]]+)\]", re.IGNORECASE)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_BARE_IMAGE_URL = re.compile(
    r"https?://[^\s<>\])\"]+"
    r"(?:s3[.-][^\s/<>\])\"]*amazonaws\.com[^\s<>\])\"]*"
    r"|\.(?:jpe?g|png|webp|gif)(?:\?[^\s<>\])\"]*)?)",
    re.IGNORECASE,
)

_MAX_IMAGES = 3


def is_image_url(url: str) -> bool:
    lower = (url or "").lower()
    if re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", lower):
        return True
    return "s3" in lower and "amazonaws.com" in lower


def _push(images: list[str], url: str) -> None:
    clean = (url or "").strip().rstrip("),.;")
    if clean and clean not in images and len(images) < _MAX_IMAGES:
        images.append(clean)


def _format_link(label: str, href: str) -> str:
    text = (label or "").strip()
    if not text or text == href:
        return href
    return f"🔗 {text}: {href}"


def format_whatsapp_reply(raw: str) -> tuple[str, list[str]]:
    """Converte Markdown de link/imagem em texto puro + URLs de mídia.

    WhatsApp não renderiza `[texto](url)` nem `![foto](url)`. A URL de catálogo
    fica visível em texto; URLs de foto saem do corpo para `/message/sendMedia`.
    """
    images: list[str] = []
    text = raw or ""

    def _take_image_tag(match: re.Match[str]) -> str:
        _push(images, match.group(1))
        return ""

    def _take_md_image(match: re.Match[str]) -> str:
        _push(images, match.group(2))
        return ""

    def _replace_md_link(match: re.Match[str]) -> str:
        label, href = match.group(1), (match.group(2) or "").strip()
        if is_image_url(href):
            _push(images, href)
            return ""
        return _format_link(label, href)

    def _take_bare_image(match: re.Match[str]) -> str:
        url = match.group(0)
        if is_image_url(url):
            _push(images, url)
            return ""
        return url

    text = _IMAGE_TAG.sub(_take_image_tag, text)
    text = _MD_IMAGE.sub(_take_md_image, text)
    text = _MD_LINK.sub(_replace_md_link, text)
    text = _BARE_IMAGE_URL.sub(_take_bare_image, text)
    text = _MD_BOLD.sub(r"*\1*", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, images


def merge_image_urls(*groups: list[str] | None) -> list[str]:
    out: list[str] = []
    for group in groups:
        for url in group or []:
            _push(out, url)
    return out
