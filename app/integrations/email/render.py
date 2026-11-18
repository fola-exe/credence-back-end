import html
import re

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def substitute(text: str, context: dict, *, subject: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        value = "" if value is None else str(value)
        if subject:
            return value.replace("\r", "").replace("\n", "")
        return html.escape(value)

    return PLACEHOLDER.sub(replace, text)


def render_email(template: dict[str, str], context: dict) -> tuple[str, str]:
    return (
        substitute(template["subject"], context, subject=True),
        substitute(template["body"], context),
    )
