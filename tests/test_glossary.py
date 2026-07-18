import pytest

from core.glossary import Glossary, GlossaryEntry, build_glossary, load_tsv, GLOSSARY_DIR


def test_core_glossary_loads_and_has_expected_terms():
    glossary = build_glossary()
    assert glossary.lookup("yield").ja == "収率"
    assert glossary.lookup("catalyst").ja == "触媒"


def test_field_glossary_adds_field_specific_terms():
    organic = build_glossary(field="organic")
    assert organic.lookup("Suzuki coupling") is not None
    # 分野固有の用語は一般用語集(coreのみ)には存在しない
    general = build_glossary(field="general")
    assert general.lookup("Suzuki coupling") is None


def test_unknown_field_raises():
    with pytest.raises(ValueError):
        build_glossary(field="astrology")


def test_user_glossary_overrides_core(tmp_path):
    user_tsv = tmp_path / "user.tsv"
    user_tsv.write_text("en\tja\tnote\nyield\t生成率(研究室独自表記)\t\n", encoding="utf-8")

    glossary = build_glossary(user_glossary_path=str(user_tsv))
    assert glossary.lookup("yield").ja == "生成率(研究室独自表記)"


def test_get_relevant_terms_only_returns_matches_in_text():
    glossary = Glossary(
        [
            GlossaryEntry(en="yield", ja="収率"),
            GlossaryEntry(en="catalyst", ja="触媒"),
            GlossaryEntry(en="cross-coupling", ja="クロスカップリング"),
        ]
    )
    hits = glossary.get_relevant_terms("The reaction gave a high yield using a Pd catalyst.")
    hit_terms = {e.en for e in hits}
    assert hit_terms == {"yield", "catalyst"}


def test_get_relevant_terms_prefers_longest_match_first_but_returns_both():
    glossary = Glossary(
        [
            GlossaryEntry(en="cross-coupling", ja="クロスカップリング"),
            GlossaryEntry(en="coupling", ja="カップリング"),
        ]
    )
    hits = glossary.get_relevant_terms("This is a cross-coupling reaction.")
    # 長い表現が先に来ること
    assert hits[0].en == "cross-coupling"


def test_load_tsv_skips_header_and_comments(tmp_path):
    tsv = tmp_path / "sample.tsv"
    tsv.write_text(
        "en\tja\tnote\n# comment line\nfoo\tフー\t\n\nbar\tバー\tnote here\n",
        encoding="utf-8",
    )
    entries = load_tsv(tsv)
    assert len(entries) == 2
    assert entries[0].en == "foo" and entries[0].ja == "フー"
    assert entries[1].note == "note here"


def test_all_bundled_field_glossaries_are_loadable():
    for field in ("organic", "inorganic", "analytical", "physical", "polymer", "materials", "computational"):
        entries = load_tsv(GLOSSARY_DIR / f"{field}.tsv")
        assert len(entries) > 0
