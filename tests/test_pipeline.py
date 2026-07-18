import json
import re
from pathlib import Path
from typing import List, Optional

import fitz

from core.glossary import Glossary, GlossaryEntry, build_glossary
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


class ContextRecordingTranslator(BaseTranslator):
    """呼び出しごとの context 引数を記録するテスト用スタブ翻訳エンジン。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen_contexts: List[Optional[str]] = []

    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        self.seen_contexts.append(context)
        return [f"訳文{i}" for i in range(len(texts))]


def test_next_batch_receives_previous_batch_tail_as_context(tmp_path, japanese_font_path):
    """回帰テスト: 段組みの都合で1つの文がバッチの境界をまたいで分割された場合でも、
    直前のバッチ最後のブロックの原文・訳文の末尾が次のバッチ呼び出しの context に
    引き継がれ、言葉選びの一貫性を保てるようにする。
    """
    input_pdf = tmp_path / "input.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for i in range(4):
        page.insert_textbox(
            fitz.Rect(72, y, 540, y + 30),
            f"This is sentence number {i} continuing the discussion of catalysts here today.",
            fontsize=10,
        )
        y += 40
    doc.save(str(input_pdf))
    doc.close()

    output_pdf = tmp_path / "output.pdf"
    translator = ContextRecordingTranslator()
    run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=translator,
        glossary=build_glossary(),
        font_path=japanese_font_path,
        batch_size=1,  # 各ブロックを別バッチにして境界をまたぐ引き継ぎを検証しやすくする
    )

    # 最初の呼び出しには当然「直前のブロック」の文脈はまだ無い
    assert translator.seen_contexts[0] is None or "直前のブロック" not in translator.seen_contexts[0]
    # 2回目以降の呼び出しには、前のバッチの訳文の引き継ぎが含まれること
    for later_context in translator.seen_contexts[1:]:
        assert later_context is not None
        assert "直前のブロック" in later_context
        assert "訳文" in later_context


def test_comparison_html_is_generated_alongside_report(tmp_path, japanese_font_path):
    """対照表示HTML(<output>.compare.html)がreport.jsonと同様に自動生成され、
    原文・訳文・フラグ・フィルタUIが含まれることを確認する。
    """
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=EchoTranslator(),
        glossary=build_glossary(),
        font_path=japanese_font_path,
    )

    compare_path = Path(report.compare_html_path)
    assert compare_path.exists()
    assert compare_path == Path(str(output_pdf.with_suffix("")) + ".compare.html")

    html_text = compare_path.read_text(encoding="utf-8")
    assert "<html" in html_text
    assert "これは翻訳結果です" in html_text  # EchoTranslatorの訳文が含まれる
    assert "A Study of Ruthenium Catalysts" in html_text  # 原文も含まれる
    assert "要注意のみ" in html_text  # フィルタUIが含まれる
    assert "data-status=" in html_text


def test_glossary_inconsistency_is_detected_and_flagged(tmp_path, japanese_font_path):
    """回帰テスト: 用語集にある英語表現が原文に出現するのに、翻訳結果に対応する
    日本語訳が含まれない場合、report.glossary_inconsistencies に記録され、
    該当ブロックに term_inconsistency フラグが付くこと。
    """
    input_pdf = tmp_path / "input.pdf"
    _make_sample_pdf(input_pdf)
    output_pdf = tmp_path / "output.pdf"

    # EchoTranslatorは常に固定文言を返すため、用語集の訳語(ルテニウム)は
    # 絶対に翻訳結果に含まれず、不一致が検出されるはず。
    glossary = Glossary([GlossaryEntry(en="Ruthenium", ja="ルテニウム")])

    report = run_pipeline(
        input_path=str(input_pdf),
        output_path=str(output_pdf),
        translator=EchoTranslator(),
        glossary=glossary,
        font_path=japanese_font_path,
    )

    assert len(report.glossary_inconsistencies) >= 1
    assert any(i["term_en"] == "Ruthenium" for i in report.glossary_inconsistencies)
    assert any(i["expected_ja"] == "ルテニウム" for i in report.glossary_inconsistencies)
