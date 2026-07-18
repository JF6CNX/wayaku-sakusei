from typing import List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from core.glossary import GlossaryEntry
from .base import BaseTranslator


class GoogleTranslator(BaseTranslator):
    """Google Cloud Translation API 実装。

    用語集連携(Glossary機能)は SPEC.md 6.3 の M5 スコープであり未実装。
    glossary_hints / context は現時点では無視される(インターフェース互換のため受け取るのみ)。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from google.cloud import translate_v2 as translate

        # GOOGLE_APPLICATION_CREDENTIALS 環境変数でサービスアカウントJSONを指すこと
        self.client = translate.Client()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        if not texts:
            return []
        results = self.client.translate(
            texts,
            source_language=self.source_lang,
            target_language="ja",
            format_="text",
        )
        return [r["translatedText"] for r in results]
