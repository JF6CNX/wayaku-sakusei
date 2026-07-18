from .base import BaseTranslator
from .claude_translator import ClaudeTranslator
from .deepl_translator import DeepLTranslator
from .google_translator import GoogleTranslator

ENGINES = {
    "claude": ClaudeTranslator,
    "deepl": DeepLTranslator,
    "google": GoogleTranslator,
}


def get_translator(engine: str, **kwargs) -> BaseTranslator:
    if engine not in ENGINES:
        raise ValueError(f"未対応の翻訳エンジンです: {engine} (対応: {list(ENGINES)})")
    return ENGINES[engine](**kwargs)
