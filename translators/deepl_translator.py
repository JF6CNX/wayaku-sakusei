import os
from typing import List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from core.glossary import GlossaryEntry
from .base import BaseTranslator


class DeepLTranslator(BaseTranslator):
    """DeepL API 実装。

    用語集連携(DeepL Glossary API)は SPEC.md 6.2 の M5 スコープであり未実装。
    glossary_hints / context は現時点では無視される(インターフェース互換のため受け取るのみ)。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        import deepl

        api_key = os.environ.get("DEEPL_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPL_API_KEY が設定されていません (.env を確認してください)")
        self.client = deepl.Translator(api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        if not texts:
            return []
        results = self.client.translate_text(
            texts,
            source_lang=self.source_lang.upper(),
            target_lang="JA",
        )
        return [r.text for r in results]
