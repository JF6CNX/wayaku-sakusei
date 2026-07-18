"""翻訳後の自動検証(SPEC.md 7章)。

書き込み前にチェックし、致命的な問題があるブロックは翻訳を破棄して
原文のまま残す(壊れた訳文を書き込むより安全)。
"""

import re
from dataclasses import dataclass, field
from typing import List, Set

from core.protect import PLACEHOLDER_PATTERN

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

# 致命的: このフラグが立ったブロックは書き込まず原文を残す
CRITICAL_FLAGS = {"missing_placeholder", "empty_translation"}

TOO_LONG_RATIO = 3.0
TOO_SHORT_RATIO = 0.2


@dataclass
class ValidationResult:
    flags: List[str] = field(default_factory=list)
    missing_placeholders: List[str] = field(default_factory=list)
    unknown_placeholders: List[str] = field(default_factory=list)
    missing_numbers: List[str] = field(default_factory=list)
    length_ratio: float = 1.0

    @property
    def is_critical(self) -> bool:
        return any(f in CRITICAL_FLAGS for f in self.flags)

    @property
    def safe_to_write(self) -> bool:
        return not self.is_critical


def _extract_numbers(text: str) -> Set[str]:
    return set(_NUMBER_RE.findall(text))


def validate_translation(
    original_text: str,
    translated_protected_text: str,
    restored_translated_text: str,
    mapping_keys: List[str],
) -> ValidationResult:
    """翻訳結果を検証する。

    Args:
        original_text: 保護前の原文ブロックテキスト
        translated_protected_text: 翻訳エンジンが返した(プレースホルダ入りの)訳文
        restored_translated_text: プレースホルダ復元後の最終訳文
        mapping_keys: protect_text が発行したプレースホルダの一覧
    """
    result = ValidationResult()

    # 1. プレースホルダ整合性チェック
    expected = set(mapping_keys)
    found_in_translation = set(PLACEHOLDER_PATTERN.findall(translated_protected_text))
    found_in_translation = {f"⟦CHEM_{n}⟧" for n in found_in_translation}

    missing = expected - found_in_translation
    unknown = found_in_translation - expected

    if missing:
        result.flags.append("missing_placeholder")
        result.missing_placeholders = sorted(missing)
    if unknown:
        result.flags.append("unknown_placeholder")
        result.unknown_placeholders = sorted(unknown)

    # 2. 空訳・原文そのままコピー
    if not restored_translated_text.strip():
        result.flags.append("empty_translation")
    elif restored_translated_text.strip() == original_text.strip():
        result.flags.append("identical_to_original")

    # 3. 数値保持チェック(原文の数値が訳文にすべて残っているか)
    original_numbers = _extract_numbers(original_text)
    translated_numbers = _extract_numbers(restored_translated_text)
    missing_numbers = original_numbers - translated_numbers
    if missing_numbers:
        result.flags.append("missing_numbers")
        result.missing_numbers = sorted(missing_numbers)

    # 4. 長さ異常
    if original_text.strip():
        ratio = len(restored_translated_text) / max(len(original_text), 1)
        result.length_ratio = ratio
        if ratio > TOO_LONG_RATIO:
            result.flags.append("too_long")
        elif ratio < TOO_SHORT_RATIO:
            result.flags.append("too_short")

    return result
