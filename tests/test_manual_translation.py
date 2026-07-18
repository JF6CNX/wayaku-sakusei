import json
from pathlib import Path

import fitz

from core.glossary import build_glossary
from core.pipeline import run_pipeline


def _make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(72, 150, 540, 230),
        "This paper reports the synthesis of a novel ruthenium complex with high "
        "catalytic activity for water oxidation reactions under mild conditions.",
        fontsize=10,
    )
    page.insert_textbox(
        fitz.Rect(72, 250, 540, 330),
        "The reaction was carried out at 25 °C for 12 h, affording the product in "
        "85% yield. The complex was characterized by NMR spectroscopy.",
        fontsize=10,
    )
    doc.save(str(path))
    doc.close()


def test_manual_file_export_when_missing(tmp_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"
    manual_file = tmp_path / "manual.json"

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(field="organic"),
        font_path=str(tmp_path / "nonexistent.ttf"),  # フォント不要(エクスポートのみ)
        manual_translation_path=str(manual_file),
    )

    assert report.manual_export_path == str(manual_file)
    assert manual_file.exists()
    assert not output_pdf.exists()

    payload = json.loads(manual_file.read_text(encoding="utf-8"))
    assert len(payload["blocks"]) == 2
    assert payload["blocks"][0]["translated_text"] is None
    assert "⟦CHEM_" in payload["blocks"][1]["protected_text"]  # 25°C/85%/NMR等が保護されている
    assert payload["context"] is not None


def test_manual_file_used_to_write_pdf_once_filled(tmp_path, japanese_font_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"
    manual_file = tmp_path / "manual.json"

    # 1回目: エクスポートのみ
    run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(field="organic"),
        font_path=str(tmp_path / "nonexistent.ttf"),
        manual_translation_path=str(manual_file),
    )

    # 人手(Claudeによる直接翻訳を想定)でtranslated_textを埋める
    payload = json.loads(manual_file.read_text(encoding="utf-8"))
    for block in payload["blocks"]:
        block["translated_text"] = block["protected_text"] + "(日本語訳)"
    manual_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2回目: 埋めたファイルを使って本番実行
    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(field="organic"),
        font_path=japanese_font_path,
        manual_translation_path=str(manual_file),
    )

    assert report.manual_export_path is None
    assert report.translated_blocks == 2
    assert output_pdf.exists()

    out_doc = fitz.open(str(output_pdf))
    page_text = out_doc[0].get_text()
    assert "日本語訳" in page_text
    assert "°C" in page_text  # プレースホルダ経由で化学表記が復元されている
    assert "85%" in page_text


def test_manual_file_rejects_mismatched_original_text(tmp_path, japanese_font_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"
    manual_file = tmp_path / "manual.json"

    run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(),
        font_path=str(tmp_path / "nonexistent.ttf"),
        manual_translation_path=str(manual_file),
    )

    payload = json.loads(manual_file.read_text(encoding="utf-8"))
    payload["blocks"][0]["original_text"] = "this no longer matches the PDF"
    payload["blocks"][0]["translated_text"] = "何か"
    manual_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    import pytest

    with pytest.raises(ValueError, match="一致しません"):
        run_pipeline(
            input_path=str(input_pdf),
            output_path=str(output_pdf),
            translator=None,
            glossary=build_glossary(),
            font_path=japanese_font_path,
            manual_translation_path=str(manual_file),
        )


def test_manual_file_leaves_null_blocks_as_original(tmp_path, japanese_font_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"
    manual_file = tmp_path / "manual.json"

    run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(),
        font_path=str(tmp_path / "nonexistent.ttf"),
        manual_translation_path=str(manual_file),
    )

    payload = json.loads(manual_file.read_text(encoding="utf-8"))
    payload["blocks"][0]["translated_text"] = "最初のブロックだけ翻訳しました。"
    # 2つ目は null のまま(未翻訳)にしておく
    manual_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(),
        font_path=japanese_font_path,
        manual_translation_path=str(manual_file),
    )

    assert report.translated_blocks == 1
    out_doc = fitz.open(str(output_pdf))
    page_text = out_doc[0].get_text()
    assert "最初のブロックだけ翻訳しました。" in page_text
    assert "The reaction was carried out at" in page_text  # 未翻訳ブロックは原文のまま
