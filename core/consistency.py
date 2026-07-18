"""用語集の訳語が実際に一貫して使われているかを、翻訳後に横断的に検証する。

各ブロックの翻訳時に用語集をプロンプトへ含めているが、LLMが実際にその訳語を
使ったとは限らない(プロンプトでの指示は「お願い」であって「強制」ではない)。
ここでは、原文に用語集の英語表現が出現し、かつそのブロックが翻訳されている
場合に、対応する日本語訳が実際に訳文中に含まれているかを機械的にチェックする。

これにより「同じ term が段落ごとに違う訳語になっていないか」を検出できる
(その段落で用語集の訳語が使われていなければ、何か別の訳語が使われた可能性が
高いため)。
"""

from dataclasses import dataclass
from typing import List, Optional, Protocol

from core.glossary import Glossary


class TranslatedBlock(Protocol):
    page_index: int
    original_text: str
    translated_text: Optional[str]


@dataclass
class ConsistencyIssue:
    block_index: int
    page_index: int
    term_en: str
    expected_ja: str
    original_text: str
    translated_text: str

    def to_dict(self) -> dict:
        return {
            "page_index": self.page_index,
            "term_en": self.term_en,
            "expected_ja": self.expected_ja,
            "original_text": self.original_text[:200],
            "translated_text": self.translated_text[:200],
        }


def check_glossary_consistency(
    results: List["TranslatedBlock"], glossary: Glossary
) -> List[ConsistencyIssue]:
    """翻訳済みブロックを走査し、用語集の訳語が使われていない箇所を報告する。"""
    entries = glossary.entries()
    if not entries:
        return []

    issues: List[ConsistencyIssue] = []
    for idx, r in enumerate(results):
        if not r.translated_text:
            continue
        original_lower = r.original_text.lower()
        for entry in entries:
            if entry.en.lower() not in original_lower:
                continue
            if entry.ja not in r.translated_text:
                issues.append(
                    ConsistencyIssue(
                        block_index=idx,
                        page_index=r.page_index,
                        term_en=entry.en,
                        expected_ja=entry.ja,
                        original_text=r.original_text,
                        translated_text=r.translated_text,
                    )
                )
    return issues
