import fitz

from core.classify import classify_blocks
from core.pdf_io import _split_lines_by_column_width, extract_blocks, write_translations


def _fake_line(x0, y0, x1, y1, text="x"):
    return {
        "bbox": (x0, y0, x1, y1),
        "spans": [{"text": text, "size": 10.0, "flags": 0}],
    }


def _make_sample_doc():
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
        fitz.Rect(72, 750, 540, 780), "Figure 1. Molecular structure of the complex under study.", fontsize=9
    )
    return doc


def test_extract_blocks_finds_expected_number_of_blocks():
    doc = _make_sample_doc()
    blocks = extract_blocks(doc)
    assert len(blocks) == 4


def test_extract_and_classify_pipeline():
    doc = _make_sample_doc()
    blocks = extract_blocks(doc)
    classify_blocks(blocks)
    classifications = [b.classification for b in blocks]
    assert classifications == ["heading", "heading", "body", "caption"]


def test_write_translations_replaces_text_in_place(japanese_font_path):
    doc = _make_sample_doc()
    blocks = extract_blocks(doc)
    classify_blocks(blocks)

    final_texts = [f"これは「{b.text[:15]}」の訳です。" for b in blocks]
    status = write_translations(doc, blocks, final_texts, font_path=japanese_font_path)

    assert status == ["written", "written", "written", "written"]
    page_text = doc[0].get_text()
    assert "これは" in page_text
    assert "A Study of Ruthenium Catalysts" not in page_text


def test_write_translations_skips_none_and_leaves_original(japanese_font_path):
    doc = _make_sample_doc()
    blocks = extract_blocks(doc)
    classify_blocks(blocks)

    final_texts = [None, None, "これは本文の訳です。", None]
    status = write_translations(doc, blocks, final_texts, font_path=japanese_font_path)

    assert status == ["skipped", "skipped", "written", "skipped"]
    page_text = doc[0].get_text()
    assert "A Study of Ruthenium Catalysts" in page_text  # 原文が残っている
    assert "Abstract" in page_text
    assert "これは本文の訳です。" in page_text


def test_overflow_leaves_original_untouched_when_translation_never_fits(japanese_font_path):
    """回帰テスト: 縮小・矩形拡張してもなお収まらない場合、原文を消さずに残すこと。

    以前は insert_textbox が失敗する前に redaction(白塗り)を実行してしまい、
    テキストが完全に失われるバグがあった。
    """
    doc = fitz.open()
    page = doc.new_page()
    # 原文("Fig. 1")自体は問題なく描画できるが、後で試みる長い日本語訳は
    # 縮小・矩形拡張(高さ130%まで)を行っても収まらない小ささにしてある
    tiny_rect = fitz.Rect(72, 750, 160, 764)
    rc = page.insert_textbox(tiny_rect, "Fig. 1", fontsize=8)
    assert rc >= 0, "テスト前提が崩れています: 原文自体が描画できていません"

    from core.classify import RawBlock

    block = RawBlock(page_index=0, rect=tuple(tiny_rect), text="Fig. 1", font_size=8, page_height=page.rect.height)

    huge_translation = "これは非常に長い翻訳文で、絶対にこの小さな矩形には収まりません。" * 5
    status = write_translations(doc, [block], [huge_translation], font_path=japanese_font_path)

    assert status == ["overflow"]
    page_text = doc[0].get_text()
    assert "Fig. 1" in page_text  # 原文が保持されている
    assert huge_translation not in page_text


def test_split_lines_by_column_width_separates_full_width_box_from_column_text():
    """回帰テスト: 全幅ボックス(要旨等)の直後に段組み本文が続く場合、
    fitzが1ブロックとして誤結合することがある。そのまま redaction すると
    隣のカラムの本文まで白塗りしてしまうため、行の右端(x1)が持続的に
    狭くなった箇所でブロックを分割する。
    """
    lines = [
        _fake_line(50, 100, 555, 113, "abstract line 1 full width"),
        _fake_line(50, 114, 555, 127, "abstract line 2 full width"),
        _fake_line(50, 128, 291, 141, "left column line 1"),
        _fake_line(50, 142, 291, 155, "left column line 2"),
        _fake_line(50, 156, 260, 169, "left column line 3 shorter end of paragraph"),
    ]

    groups = _split_lines_by_column_width(lines)

    assert len(groups) == 2
    assert len(groups[0]) == 2  # 要旨部分(全幅の2行)
    assert len(groups[1]) == 3  # 左カラム部分(3行、最後の行が短くても同じグループ)


def test_split_lines_by_column_width_does_not_split_on_natural_paragraph_end():
    """段落最後の1行が短くなるのは普通のことなので、それだけでは分割しない。"""
    lines = [
        _fake_line(50, 100, 291, 113, "left column line 1"),
        _fake_line(50, 114, 291, 127, "left column line 2"),
        _fake_line(50, 128, 150, 141, "short last line"),
    ]

    groups = _split_lines_by_column_width(lines)

    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_extract_blocks_splits_merged_abstract_and_column_block():
    """全幅の要旨ボックスと段組み本文が同じブロックに誤結合された場合でも、
    抽出結果では別ブロックとして分離され、右カラムの矩形と重ならないこと。
    """
    doc = fitz.open()
    page = doc.new_page()

    # 実PDFでの誤結合パターン自体は _split_lines_by_column_width の単体テスト(上記)で
    # 検証済み。ここでは分割後のブロックのx1が右カラムまではみ出さないことを
    # extract_blocks 経由でも確認する。
    page.insert_textbox(
        fitz.Rect(50, 100, 291, 250),
        "Left column paragraph that stays within the left half of the page only, "
        "wrapping across several lines to fill the column completely for this test.",
        fontsize=10,
    )
    page.insert_textbox(
        fitz.Rect(315, 100, 555, 250),
        "Right column paragraph that stays within the right half of the page only, "
        "wrapping across several lines to fill the column completely for this test.",
        fontsize=10,
    )
    blocks = extract_blocks(doc)
    left = [b for b in blocks if b.rect[0] < 300]
    right = [b for b in blocks if b.rect[0] >= 300]
    assert left and right
    for b in left:
        assert b.rect[2] <= 300  # 左カラムのブロックが右カラムまではみ出していない


def test_multiline_translation_fits_a_wide_short_bar(japanese_font_path):
    """回帰テスト: ACCESSバーのような「横長・低い」矩形に、原文の行数を
    引きずった複数行の訳文(改行区切り)を渡しても、改行を自然な折り返しに
    変換して1〜2行程度に収め、原文のまま残さないこと。
    """
    doc = fitz.open()
    page = doc.new_page()
    from core.classify import RawBlock

    wide_short_rect = (50, 200, 540, 215)  # 幅490pt, 高さ15ptの横長バー
    block = RawBlock(page_index=0, rect=wide_short_rect, text="ACCESS", font_size=9, page_height=page.rect.height)

    multiline_translation = "アクセス\nメトリクスとその他\n記事の推薦\nサポート情報"
    status = write_translations(doc, [block], [multiline_translation], font_path=japanese_font_path)

    assert status == ["written"]


def test_normalize_for_layout_collapses_newlines_but_keeps_heading_break():
    from core.pdf_io import _normalize_for_layout

    text = "これは要旨の本文です。\n■緒言\nこれは緒言の本文です。"
    normalized = _normalize_for_layout(text)

    assert normalized == "これは要旨の本文です。\n■緒言 これは緒言の本文です。"
    assert normalized.count("\n") == 1


def test_overlapping_source_rects_are_merged_instead_of_colliding(japanese_font_path):
    """回帰テスト: 数式が密に組版されたページでは、原文抽出の時点で隣接ブロックの
    矩形がすでに重なっていることがある(例: 長い説明文の末尾が次のブロックの
    先頭と同じ高さまで垂れ込む)。これらを別々に白塗り・描画すると訳文同士が
    重なって表示されてしまうため、重なりのあるブロックは1つにまとめて描画する。
    """
    from core.classify import RawBlock

    doc = fitz.open()
    page = doc.new_page()

    block_a = RawBlock(
        page_index=0,
        rect=(50, 100, 300, 300),
        text="Long explanatory sentence part one leading into a symbol.",
        font_size=10,
        page_height=page.rect.height,
    )
    block_b = RawBlock(
        page_index=0,
        rect=(50, 290, 300, 330),  # block_a と 10pt 重なっている
        text="continuation referring to the same symbol r",
        font_size=10,
        page_height=page.rect.height,
    )

    translated = ["これは1つ目の説明文である。", "これはrに関する続きの説明である。"]
    status = write_translations(doc, [block_a, block_b], translated, font_path=japanese_font_path)

    assert status == ["written", "written"]

    page_text = doc[0].get_text()
    assert "これは1つ目の説明文である。" in page_text
    assert "これはrに関する続きの説明である。" in page_text


def test_table_data_block_keeps_line_breaks_instead_of_flowing_together(japanese_font_path):
    """回帰テスト: table_data に分類されたブロックは、改行を空白に変換する
    通常のレイアウト正規化をバイパスし、行ごとの区切りを保ったまま描画する
    (数値と訳語が1つの流れる段落として混ざり合わないようにするため)。
    """
    from core.classify import RawBlock

    doc = fitz.open()
    page = doc.new_page()

    block = RawBlock(
        page_index=0,
        rect=(50, 100, 300, 400),
        text="amide methylation\n10\n11\n16\n119\n34",
        font_size=9,
        page_height=page.rect.height,
        classification="table_data",
    )
    translated = ["アミドメチル化\n10\n11\n16\n119\n34"]
    status = write_translations(doc, [block], translated, font_path=japanese_font_path)

    assert status == ["written"]

    d = doc[0].get_text("dict")
    line_texts = [
        "".join(span["text"] for span in line["spans"])
        for b in d["blocks"]
        if b.get("type") == 0
        for line in b["lines"]
    ]
    # "10", "11" 等が別々の行として描画されている(1行に結合されていない)こと
    assert "10" in line_texts
    assert "11" in line_texts


def test_dehyphenate_joins_word_broken_across_line_wrap():
    """回帰テスト: "organo-\\nmetallic" のように行末ハイフンで分断された単語を
    結合する。翻訳エンジンに分断された単語をそのまま渡すと誤訳の原因になる。
    """
    from core.pdf_io import _dehyphenate

    assert _dehyphenate("organo-\nmetallic systems") == "organometallic systems"
    assert _dehyphenate("high-\nthroughput screening") == "highthroughput screening"


def test_dehyphenate_does_not_join_across_uppercase_boundary():
    """大文字が続く場合(新しい文・固有名詞の可能性)は結合しない。"""
    from core.pdf_io import _dehyphenate

    text = "a stable complex-\nSMILES was generated"
    assert _dehyphenate(text) == text  # 変化しないこと
