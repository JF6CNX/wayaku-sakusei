import json
import re
from pathlib import Path
from typing import List, Optional

import fitz

from core.glossary import GlossaryEntry, build_glossary
from core.pipeline import run_pipeline
from translators.base import BaseTranslator

_PLACEHOLDER_RE = re.compile(r"⟦CHEM_\d+⟧")


class EchoTranslator(BaseTranslator):
    """API不要のテスト用スタブ翻訳エンジン。

    原文の英単語は残さず、プレースホルダだけを保持した固定の日本語風テキストに
    差し替える(実際にPDF上で原文が消えたことを検証できるようにするため)。
    """

    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        out = []
        for t in texts:
            placeholders = _PLACEHOLDER_RE.findall(t)
            out.append("これは翻訳結果です" + "".join(placeholders) + "。")
        return out


def _make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 80, 540, 110), "A Study of Ruthenium Catalysts", fontsize=16, fontname="hebo")
    page.insert_textbox(fitz.Rect(72, 120, 540, 145), "Abstract", fontsize=13, fontname="hebo")
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


def test_dry_run_does_not_require_font_or_write_output(tmp_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=None,
        glossary=build_glossary(),
        font_path=str(tmp_path / "nonexistent.ttf"),
        dry_run=True,
    )

    assert report.total_blocks == 4
    assert not output_pdf.exists()


def test_full_pipeline_translates_and_writes_report(tmp_path, japanese_font_path):
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"
    review_tsv = tmp_path / "review.tsv"

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=EchoTranslator(),
        glossary=build_glossary(field="organic"),
        font_path=japanese_font_path,
        review_tsv_path=str(review_tsv),
    )

    assert output_pdf.exists()
    assert report.translated_blocks == report.total_blocks
    assert report.failed_validation == []
    assert report.layout_overflow == []
    assert "yield" in report.glossary_terms_used
    assert "catalytic" in report.glossary_terms_used

    report_json_path = Path(str(output_pdf.with_suffix("")) + ".report.json")
    assert report_json_path.exists()
    with open(report_json_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["translated_blocks"] == report.translated_blocks

    assert review_tsv.exists()
    review_content = review_tsv.read_text(encoding="utf-8")
    assert "これは翻訳結果です" in review_content

    out_doc = fitz.open(str(output_pdf))
    page_text = out_doc[0].get_text()
    assert "これは翻訳結果です" in page_text
    assert "A Study of Ruthenium Catalysts" not in page_text  # 原文は置換された
    assert "Ruthenium" not in page_text
    # 化学表記(°Cや85%)がプレースホルダ経由で正しく復元されていること
    assert "°C" in page_text
    assert "85%" in page_text


def test_pages_filter_limits_processed_blocks(tmp_path, japanese_font_path):
    input_pdf = tmp_path / "input.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_textbox(
        fitz.Rect(72, 150, 540, 230),
        "This paper reports the synthesis of a novel catalyst for oxidation reactions today.",
        fontsize=10,
    )
    page2 = doc.new_page()
    page2.insert_textbox(
        fitz.Rect(72, 150, 540, 230),
        "The second page discusses further characterization of the catalyst system used here.",
        fontsize=10,
    )
    doc.save(str(input_pdf))
    doc.close()

    output_pdf = tmp_path / "output.pdf"
    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=EchoTranslator(),
        glossary=build_glossary(),
        font_path=japanese_font_path,
        pages=[1],
    )

    assert report.total_blocks == 1

    out_doc = fitz.open(str(output_pdf))
    assert "これは翻訳結果です" in out_doc[0].get_text()
    assert "second page discusses" in out_doc[1].get_text()  # 対象外ページは原文のまま
