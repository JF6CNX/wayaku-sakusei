from core.protect import find_surviving_placeholders, protect_text, restore_text


def test_roundtrip_preserves_original_text():
    text = (
        "The reaction was carried out at 25 °C for 12 h, affording the product in "
        "85% yield. The complex [Ru(bpy)3]2+ was characterized by NMR and HRMS. "
        "See DOI: 10.1021/jacs.0c00001 for details. CAS 50-00-0."
    )
    protected, mapping = protect_text(text)
    assert protected != text
    assert restore_text(protected, mapping) == text


def test_chemical_formula_is_protected():
    text = "The product Fe2O3 was dissolved in CH3CH2OH before analysis."
    protected, mapping = protect_text(text)
    originals = set(mapping.values())
    assert "Fe2O3" in originals
    assert "CH3CH2OH" in originals


def test_percent_unit_is_protected():
    # % is a non-word character; a naive \b-based regex fails to match it (regression test)
    text = "The yield was 85% under these conditions."
    protected, mapping = protect_text(text)
    assert "85%" in mapping.values()
    assert "85%" not in protected


def test_spectral_data_line_is_protected_as_a_whole():
    text = "1H NMR (400 MHz, CDCl3): δ 7.26 (s, 1H), 3.45 (m, 2H)."
    protected, mapping = protect_text(text)
    assert len(mapping) == 1
    (placeholder,) = mapping.keys()
    assert mapping[placeholder] == text
    assert protected == placeholder


def test_abbreviations_are_protected():
    text = "The product was purified by HPLC and dried using THF as solvent."
    protected, mapping = protect_text(text)
    originals = set(mapping.values())
    assert "HPLC" in originals
    assert "THF" in originals


def test_plain_english_sentence_is_left_mostly_untouched():
    text = "This paper reports the synthesis of a novel catalyst for oxidation reactions."
    protected, mapping = protect_text(text)
    assert protected == text
    assert mapping == {}


def test_bold_compound_label_tokens_are_protected_when_provided():
    text = "Compound 2a was obtained in high yield, and 2a was further purified."
    protected, mapping = protect_text(text, bold_tokens=["2a"])
    assert "2a" not in protected
    assert "2a" in mapping.values()


def test_bold_ordinary_words_are_not_treated_as_compound_labels():
    # 論文のタイトル・見出しが太字で組まれるのは一般的。太字というだけで
    # 化合物番号扱いにすると、見出し全体が翻訳できなくなってしまう(回帰テスト)。
    text = "A Study of Ruthenium Catalysts"
    protected, mapping = protect_text(text, bold_tokens=["A", "Study", "of", "Ruthenium", "Catalysts"])
    assert protected == text
    assert mapping == {}


def test_find_surviving_placeholders_detects_leftovers():
    text = "The reaction gave 85% yield."
    protected, _ = protect_text(text)
    survivors = find_surviving_placeholders(protected)
    assert len(survivors) == 1
    assert survivors[0] in protected
