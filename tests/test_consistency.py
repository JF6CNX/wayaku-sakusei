from dataclasses import dataclass, field
from typing import List, Optional

from core.consistency import check_glossary_consistency
from core.glossary import Glossary, GlossaryEntry


@dataclass
class FakeResult:
    page_index: int
    original_text: str
    translated_text: Optional[str] = None
    flags: List[str] = field(default_factory=list)


def _glossary():
    return Glossary(
        [
            GlossaryEntry(en="transition state", ja="遷移状態"),
            GlossaryEntry(en="conformer", ja="立体配座"),
        ]
    )


def test_consistent_translation_reports_no_issue():
    results = [
        FakeResult(0, "The transition state was optimized.", "遷移状態が最適化された。"),
        FakeResult(0, "Multiple conformers were generated.", "複数の立体配座が生成された。"),
    ]
    issues = check_glossary_consistency(results, _glossary())
    assert issues == []


def test_missing_glossary_translation_is_flagged():
    results = [
        FakeResult(0, "The transition state was optimized.", "TSが最適化された。"),  # 遷移状態が使われていない
    ]
    issues = check_glossary_consistency(results, _glossary())
    assert len(issues) == 1
    assert issues[0].term_en == "transition state"
    assert issues[0].expected_ja == "遷移状態"
    assert issues[0].block_index == 0


def test_untranslated_blocks_are_skipped():
    results = [
        FakeResult(0, "The transition state was optimized.", None),
    ]
    issues = check_glossary_consistency(results, _glossary())
    assert issues == []


def test_term_not_present_in_original_is_not_checked():
    results = [
        FakeResult(0, "This sentence has nothing to do with chemistry terms.", "これは化学用語とは無関係な文である。"),
    ]
    issues = check_glossary_consistency(results, _glossary())
    assert issues == []


def test_empty_glossary_reports_no_issues():
    results = [
        FakeResult(0, "The transition state was optimized.", "TSが最適化された。"),
    ]
    issues = check_glossary_consistency(results, Glossary([]))
    assert issues == []


def test_multiple_blocks_with_inconsistent_translation_are_all_flagged():
    results = [
        FakeResult(0, "The conformer was stable.", "立体配座は安定していた。"),  # OK
        FakeResult(1, "Another conformer was found.", "別のコンフォーマーが見つかった。"),  # 訳語が違う
    ]
    issues = check_glossary_consistency(results, _glossary())
    assert len(issues) == 1
    assert issues[0].block_index == 1
    assert issues[0].term_en == "conformer"
