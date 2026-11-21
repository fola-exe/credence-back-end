from app.core.config import Settings, settings
from app.integrations.kora.provider import DemoKoraProvider, KoraProvider, RealKoraProvider


def get_kora_provider(config: Settings | None = None) -> KoraProvider:
    current = config or settings
    if current.kora_demo_enabled:
        return DemoKoraProvider(current)
    return RealKoraProvider(current)
