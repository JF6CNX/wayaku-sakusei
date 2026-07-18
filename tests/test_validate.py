from core.protect import protect_text, restore_text
from core.validate import validate_translation


def _translate_stub(protected_text: str, mutate=None) -> str:
    """プレースホルダを保ったまま、周囲のテキストだけ雑に「翻訳」するテスト用スタブ。"""
    translated = protected_text.replace("The reaction gave", "反応は").replace(
        "yield", "収率"
    )
    if mutate:
        translated = mutate(translated)
    return translated


def test_good_translation_passes_validation():
    original = "The reaction gave 85% yield at 25 °C."
    protected, mapping = protect_text(original)
    translated_protected = _translate_stub(protected)
    restored = restore_text(translated_protected, mapping)

    result = validate_translation(original, translated_protected, restored, list(mapping.keys()))
    assert result.flags == []
    assert result.safe_to_write


def test_missing_placeholder_is_flagged_critical():
    original = "The reaction gave 85% yield at 25 °C."
    protected, mapping = protect_text(original)
    placeholder_to_drop = next(iter(mapping.keys()))

    translated_protected = _translate_stub(protected, mutate=lambda t: t.replace(placeholder_to_drop, ""))
    restored = restore_text(translated_protected, mapping)

    result = validate_translation(original, translated_protected, restored, list(mapping.keys()))
    assert "missing_placeholder" in result.flags
    assert not result.safe_to_write


def test_missing_number_is_flagged():
    original = "The yield was 85 percent."  # "85" is not protected (no unit token attached)
    protected, mapping = protect_text(original)
    translated_protected = protected.replace("85", "eighty-five")
    restored = restore_text(translated_protected, mapping)

    result = validate_translation(original, translated_protected, restored, list(mapping.keys()))
    assert "missing_numbers" in result.flags
    assert "85" in result.missing_numbers


def test_empty_translation_is_flagged_critical():
    original = "The reaction gave 85% yield."
    protected, mapping = protect_text(original)
    result = validate_translation(original, "", "", list(mapping.keys()))
    assert "empty_translation" in result.flags
    assert not result.safe_to_write


def test_identical_to_original_is_flagged_but_not_critical():
    original = "The reaction gave a good result."
    protected, mapping = protect_text(original)
    result = validate_translation(original, protected, original, list(mapping.keys()))
    assert "identical_to_original" in result.flags
    assert result.safe_to_write


def test_too_long_translation_is_flagged():
    original = "OK."
    translated = "This is a very very very very very very very long unrelated translation output."
    result = validate_translation(original, translated, translated, [])
    assert "too_long" in result.flags


def test_too_short_translation_is_flagged():
    original = "This is a reasonably long original English sentence about chemistry."
    translated = "short"
    result = validate_translation(original, translated, translated, [])
    assert "too_short" in result.flags
