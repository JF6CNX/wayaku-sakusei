from core.classify import RawBlock, classify_blocks

PAGE_H = 792.0


def _block(page_index, y0, y1, text, font_size=10.0, x0=50.0, x1=500.0):
    return RawBlock(page_index=page_index, rect=(x0, y0, x1, y1), text=text, font_size=font_size, page_height=PAGE_H)


def test_body_paragraph_classified_as_body():
    blocks = [
        _block(
            0,
            200,
            260,
            "This paper reports the synthesis of a novel ruthenium complex with high "
            "catalytic activity for water oxidation.",
        )
    ]
    classify_blocks(blocks)
    assert blocks[0].classification == "body"


def test_known_heading_classified_as_heading():
    blocks = [
        _block(0, 200, 260, "This paper reports the synthesis of a novel catalyst for oxidation."),
        _block(0, 300, 320, "Abstract", font_size=14),
    ]
    classify_blocks(blocks)
    assert blocks[1].classification == "heading"


def test_figure_caption_classified_as_caption():
    blocks = [_block(0, 300, 320, "Figure 1. Crystal structure of the complex.")]
    classify_blocks(blocks)
    assert blocks[0].classification == "caption"


def test_header_footer_classified_by_margin():
    blocks = [_block(0, 10, 30, "Journal of Chemistry, Vol. 12")]
    classify_blocks(blocks)
    assert blocks[0].classification == "header_footer"


def test_author_affiliation_on_first_page_before_heading():
    blocks = [
        _block(0, 100, 120, "John Smith, Jane Doe"),
        _block(0, 130, 150, "Department of Chemistry, University of Tokyo, john@example.com"),
    ]
    classify_blocks(blocks)
    assert blocks[1].classification == "author_affil"


def test_references_heading_switches_subsequent_blocks_to_reference():
    blocks = [
        _block(0, 200, 260, "This paper reports the synthesis of a novel catalyst for oxidation."),
        _block(1, 100, 120, "References", font_size=14),
        _block(1, 130, 150, "1. Smith, J. et al. J. Am. Chem. Soc. 2020, 142, 1234."),
    ]
    classify_blocks(blocks)
    assert blocks[1].classification == "heading"
    assert blocks[2].classification == "reference"


def test_chemical_formula_block_classified_as_formula():
    blocks = [_block(0, 300, 320, "[Ru(bpy)3]2+ Fe2O3 CH3CH2OH")]
    classify_blocks(blocks)
    assert blocks[0].classification == "formula"


def test_acknowledgment_classified_as_footnote():
    blocks = [_block(0, 300, 320, "Acknowledgments: We thank the funding agency for support.")]
    classify_blocks(blocks)
    assert blocks[0].classification == "footnote"


def test_equation_symbol_fragments_classified_as_equation():
    """回帰テスト: 数式は文字ごとに精密配置されるため、PDF抽出時に
    'n\\nPREi'や'r\\nr\\ni'のような無意味な断片ブロックに分解されることが多い。
    こうした断片は他の分類に一致しないまま "uncertain" として翻訳対象に
    入ってしまうと、実翻訳エンジンで数式を破壊しかねないため、
    "equation" として検出し除外する。
    """
    blocks = [
        _block(0, 400, 410, "n\nPREi"),
        _block(0, 411, 421, "r\nr\ni"),
        _block(0, 422, 432, "(2)"),
        _block(0, 433, 443, "clusters,"),
    ]
    classify_blocks(blocks)
    assert all(b.classification == "equation" for b in blocks)


def test_long_explanatory_prose_not_misclassified_as_equation():
    """数式の周囲にある長い説明文(1行あたりの文字数が多い)は、
    途中に数式記号を含んでいても equation 扱いにしない。
    """
    blocks = [
        _block(
            0,
            400,
            460,
            "r (how many conformers of method i are in\na cluster of the combined "
            "ensemble and not filtered out in the\ncombination step) and the recall "
            "of method i, RECi",
        )
    ]
    classify_blocks(blocks)
    assert blocks[0].classification != "equation"


def test_equation_is_excluded_from_translation():
    from core.classify import EXCLUDED_CLASSIFICATIONS

    assert "equation" in EXCLUDED_CLASSIFICATIONS


def test_reference_list_detected_without_explicit_heading():
    """回帰テスト: 論文によっては「REFERENCES」という見出しテキストを持たず、
    いきなり "(1) Author, A. ..." のような番号付き引用から始まることがある。
    見出しが無くても、文献番号(1)から始まるブロックを検出して以降を
    reference として扱う(既定で翻訳対象から除外するため)。
    """
    blocks = [
        _block(0, 300, 320, "Some concluding sentence of the main text goes here."),
        _block(
            1,
            100,
            120,
            "(1) Bozal-Ginesta, C.; Pablo-García, S. Machine learning for catalysis.",
        ),
        _block(1, 130, 150, "(4) Pracht, P.; Bohle, F.; Grimme, S. Automated exploration."),
    ]
    classify_blocks(blocks)
    assert blocks[1].classification == "reference"
    assert blocks[2].classification == "reference"


def test_inline_roman_numeral_list_not_misdetected_as_reference_list():
    """"(i) ..." のようなローマ数字の列挙は参考文献リストの開始とは判定しない。"""
    blocks = [
        _block(
            0,
            300,
            360,
            "An ideal conformer generator has five properties: (i) be inexpensive, "
            "(ii) be exhaustive, (iii) be valid, (iv) be accurate, and (v) be integrable.",
        )
    ]
    classify_blocks(blocks)
    assert blocks[0].classification != "reference"


def test_borderless_table_data_detected_by_numeric_line_ratio():
    """回帰テスト: 罫線の無い表は、ラベル行と数値のみの行が交互に並んだ1つの
    ブロックとして抽出される(表1のような反応名+複数手法の数値列)。これを
    通常の文章として改行結合すると、数値と単語が入り乱れた読めない塊になる
    ため、"table_data" として検出し改行を保持する対象にする。
    """
    lines = []
    for name in ["amide methylation", "cyclization", "epoxidation", "hydride transfer", "peptide"]:
        lines.append(name)
        lines.extend(["10", "11", "16", "119", "34"])
    text = "\n".join(lines)

    blocks = [_block(0, 300, 700, text)]
    classify_blocks(blocks)
    assert blocks[0].classification == "table_data"


def test_ordinary_prose_with_a_few_numbers_not_misdetected_as_table_data():
    blocks = [
        _block(
            0,
            300,
            360,
            "The reaction was carried out at 25 °C for 12 h, affording the product "
            "in 85% yield after purification by column chromatography on silica gel.",
        )
    ]
    classify_blocks(blocks)
    assert blocks[0].classification != "table_data"
