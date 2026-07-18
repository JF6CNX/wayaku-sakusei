import json
import os
from typing import List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from core.glossary import GlossaryEntry
from .base import BaseTranslator

_FIELD_LABELS = {
    "organic": "有機合成化学",
    "inorganic": "無機化学",
    "analytical": "分析化学",
    "physical": "物理化学",
    "polymer": "高分子化学",
    "materials": "材料化学",
    "general": "化学",
}

_BASE_SYSTEM_PROMPT = """あなたは化学系学術論文の専門翻訳者です。与えられる英語のテキストブロックを
自然で正確な日本語(である調・学術文体)に翻訳してください。

厳守事項:
1. `⟦CHEM_nnn⟧` の形式のプレースホルダ(例: ⟦CHEM_001⟧)は、化学式・単位付き数値・
   スペクトルデータ・略語などを保護するために埋め込まれています。これらは絶対に
   改変・削除・翻訳せず、出力中に元の位置関係を保ったまま残してください。
2. 数値・有効数字・不等号・±表記は改変しないでください。
3. 専門用語は下記の用語集に従ってください。用語集にない専門用語は化学論文として
   自然な定訳を使ってください。
4. 固有名詞・化合物番号・引用番号([1]など)はそのまま残してください。
5. 入力はJSON配列(文字列のリスト)です。出力も同じ要素数のJSON配列のみを返し、
   説明文や前後のコメントは一切付けないでください。
"""


def _format_glossary(glossary_hints: Optional[List[GlossaryEntry]]) -> str:
    if not glossary_hints:
        return "(このバッチに該当する用語集エントリはありません)"
    lines = [f"- {e.en} → {e.ja}" + (f" ({e.note})" if e.note else "") for e in glossary_hints]
    return "\n".join(lines)


class ClaudeTranslator(BaseTranslator):
    def __init__(
        self,
        model: str = "claude-sonnet-5",
        field: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        from anthropic import Anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY が設定されていません (.env を確認してください)")
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.field_label = _FIELD_LABELS.get(field or "general", _FIELD_LABELS["general"])

    def _build_system_prompt(
        self, glossary_hints: Optional[List[GlossaryEntry]], context: Optional[str]
    ) -> str:
        parts = [_BASE_SYSTEM_PROMPT, f"\n本論文の分野: {self.field_label}"]
        if context:
            parts.append(f"\n論文の主題(タイトル・要旨より):\n{context}")
        parts.append(f"\n用語集(この訳語を優先すること):\n{_format_glossary(glossary_hints)}")
        return "\n".join(parts)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        if not texts:
            return []

        system_prompt = self._build_system_prompt(glossary_hints, context)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": json.dumps(texts, ensure_ascii=False)}],
        )
        raw = message.content[0].text
        translated = json.loads(raw)

        if len(translated) != len(texts):
            raise ValueError(
                f"翻訳結果の件数が一致しません (入力{len(texts)}件 / 出力{len(translated)}件)"
            )
        return translated
