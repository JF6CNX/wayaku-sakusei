import json
from pathlib import Path

from core.glossary import load_tsv
from core.glossary_learning import export_learning_candidates, import_learned_terms


def _make_source_file(path: Path) -> None:
    payload = {
        "blocks": [
            {
                "block_id": 0,
                "original_text": "The conformer ensemble was generated using metadynamics.",
                "translated_text": "立体配座アンサンブルはメタダイナミクスを用いて生成された。",
            },
            {
                "block_id": 1,
                "original_text": "Author names here.",
                "translated_text": None,  # 未翻訳ブロックは候補抽出の対象外
            },
            {
                "block_id": 2,
                "original_text": "The transition state was optimized at the DFT level.",
                "translated_text": "遷移状態はDFTレベルで最適化された。",
            },
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_export_learning_candidates_skips_untranslated_blocks(tmp_path):
    source = tmp_path / "source.json"
    _make_source_file(source)
    learn_file = tmp_path / "learn.json"

    count = export_learning_candidates(source, learn_file)

    assert count == 2  # block_id=1 (translated_text=None) は含まれない
    payload = json.loads(learn_file.read_text(encoding="utf-8"))
    assert len(payload["pairs"]) == 2
    assert all(p["candidate_terms"] == [] for p in payload["pairs"])
    assert "instructions" in payload


def test_import_learned_terms_creates_new_glossary_file(tmp_path):
    learn_file = tmp_path / "learn.json"
    payload = {
        "pairs": [
            {
                "original_text": "The conformer ensemble was generated using metadynamics.",
                "translated_text": "立体配座アンサンブルはメタダイナミクスを用いて生成された。",
                "candidate_terms": [
                    {"en": "conformer ensemble", "ja": "立体配座アンサンブル", "note": ""},
                    {"en": "metadynamics", "ja": "メタダイナミクス", "note": ""},
                ],
            }
        ]
    }
    learn_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    glossary_file = tmp_path / "learned.tsv"
    result = import_learned_terms(learn_file, glossary_file)

    assert len(result.added) == 2
    assert glossary_file.exists()

    entries = {e.en: e.ja for e in load_tsv(glossary_file)}
    assert entries["conformer ensemble"] == "立体配座アンサンブル"
    assert entries["metadynamics"] == "メタダイナミクス"


def test_import_learned_terms_merges_with_existing_file(tmp_path):
    glossary_file = tmp_path / "learned.tsv"
    glossary_file.write_text("en\tja\tnote\nyield\t収率\t\n", encoding="utf-8")

    learn_file = tmp_path / "learn.json"
    payload = {
        "pairs": [
            {
                "original_text": "...",
                "translated_text": "...",
                "candidate_terms": [{"en": "conformer", "ja": "立体配座", "note": ""}],
            }
        ]
    }
    learn_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = import_learned_terms(learn_file, glossary_file)

    assert len(result.added) == 1
    entries = {e.en: e.ja for e in load_tsv(glossary_file)}
    assert entries["yield"] == "収率"  # 既存エントリは維持される
    assert entries["conformer"] == "立体配座"  # 新規エントリが追加される


def test_import_learned_terms_skips_exact_duplicate(tmp_path):
    glossary_file = tmp_path / "learned.tsv"
    glossary_file.write_text("en\tja\tnote\nconformer\t立体配座\t\n", encoding="utf-8")

    learn_file = tmp_path / "learn.json"
    payload = {
        "pairs": [
            {
                "original_text": "...",
                "translated_text": "...",
                "candidate_terms": [{"en": "conformer", "ja": "立体配座", "note": ""}],
            }
        ]
    }
    learn_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = import_learned_terms(learn_file, glossary_file)

    assert result.added == []
    assert result.skipped_duplicates == ["conformer"]


def test_import_learned_terms_reports_conflict_without_overwriting(tmp_path):
    glossary_file = tmp_path / "learned.tsv"
    glossary_file.write_text("en\tja\tnote\nconformer\t立体配座\t\n", encoding="utf-8")

    learn_file = tmp_path / "learn.json"
    payload = {
        "pairs": [
            {
                "original_text": "...",
                "translated_text": "...",
                "candidate_terms": [{"en": "conformer", "ja": "配座異性体", "note": ""}],
            }
        ]
    }
    learn_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = import_learned_terms(learn_file, glossary_file)

    assert result.added == []
    assert len(result.conflicts) == 1
    assert result.conflicts[0] == {
        "en": "conformer",
        "existing_ja": "立体配座",
        "new_ja": "配座異性体",
    }
    # 既存の訳語は上書きされていないこと
    entries = {e.en: e.ja for e in load_tsv(glossary_file)}
    assert entries["conformer"] == "立体配座"


def test_import_learned_terms_conflict_within_same_batch(tmp_path):
    glossary_file = tmp_path / "learned.tsv"  # 新規(まだ存在しない)

    learn_file = tmp_path / "learn.json"
    payload = {
        "pairs": [
            {
                "original_text": "a",
                "translated_text": "a",
                "candidate_terms": [{"en": "conformer", "ja": "立体配座", "note": ""}],
            },
            {
                "original_text": "b",
                "translated_text": "b",
                "candidate_terms": [{"en": "conformer", "ja": "コンフォマー", "note": ""}],
            },
        ]
    }
    learn_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = import_learned_terms(learn_file, glossary_file)

    # バッチ内で食い違う場合は両方登録せず、conflictとして報告する
    assert result.added == []
    assert len(result.conflicts) == 1
