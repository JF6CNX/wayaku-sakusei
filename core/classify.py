"""抽出したPDFテキストブロックの分類(SPEC.md 3章)。

分類結果は以下のいずれか:
    body / heading / caption / formula / equation / table_data / reference /
    header_footer / author_affil / footnote / uncertain
"""

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from core.protect import FORMULA_RE

HEADER_MARGIN = 50.0
FOOTER_MARGIN = 50.0
MIN_BODY_CHARS = 40

_KNOWN_HEADINGS = {
    "abstract",
    "introduction",
    "results and discussion",
    "results",
    "discussion",
    "experimental section",
    "experimental",
    "materials and methods",
    "general procedure",
    "conclusion",
    "conclusions",
    "acknowledgment",
    "acknowledgments",
    "acknowledgement",
    "acknowledgements",
    "supporting information",
    "references",
    "bibliography",
}

_REFERENCE_HEADINGS = {"references", "bibliography"}

_CAPTION_RE = re.compile(r"^(Figure|Fig\.|Table|Scheme|Chart)\s*\d+", re.IGNORECASE)

_FOOTNOTE_KEYWORDS = re.compile(
    r"Acknowledg|Conflict of interest|Supporting Information|Author Contributions",
    re.IGNORECASE,
)

_AFFIL_KEYWORDS = re.compile(r"Department|University|Institute|Laboratory|College", re.IGNORECASE)

_SENTENCE_END_RE = re.compile(r"[.?!。\"']\s*$")

# 一部の論文は「REFERENCES」という見出しテキストを持たず、いきなり
# "(1) Author, A. ..." のような番号付き引用から参考文献リストが始まる。
# 見出しが無くても、文献番号(1)から始まるブロックを検出して以降を
# reference 扱いにする(通常の "(i)" のような列挙と混同しないよう、
# 文献番号は具体的に "(1)" から始まるものに限定する)。
_REFERENCE_LIST_START_RE = re.compile(r"^\(1\)\s")


@dataclass
class RawBlock:
    """PDFから抽出したテキストブロック(fitz非依存の中間表現)。"""

    page_index: int
    rect: Tuple[float, float, float, float]  # x0, y0, x1, y1
    text: str
    font_size: float = 10.0
    page_height: float = 792.0
    bold_ratio: float = 0.0
    bold_tokens: List[str] = field(default_factory=list)
    classification: Optional[str] = field(default=None)


def _looks_like_formula(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    formula_tokens = sum(1 for t in tokens if FORMULA_RE.fullmatch(t.strip(",.;()")))
    return formula_tokens / len(tokens) > 0.6


# 数式(LaTeX的な組版で文字ごとに精密配置された式)は、PDFテキスト抽出時に
# 「n」「PREi」「r\nr\ni」のような無意味な断片ブロックへバラバラに分解されることが多い。
# 通常の文章は1行あたりの文字数が多い(単語・文が続く)のに対し、数式断片は
# 1行あたりの文字数が極端に少ない(記号や1〜2文字の変数名のみ)ため、
# 「1行あたりの平均文字数」を数式断片の判定に用いる。
EQUATION_AVG_CHARS_PER_LINE_THRESHOLD = 15.0


def _looks_like_equation_fragment(text: str) -> bool:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    avg_chars_per_line = sum(len(line) for line in lines) / len(lines)
    return avg_chars_per_line <= EQUATION_AVG_CHARS_PER_LINE_THRESHOLD


# 罫線の無い(=find_tablesで検出できない)表の本文は、抽出時に
# 「ラベル\n数値\n数値\n数値\n数値\n数値\n次のラベル\n...」のように
# セルの中身が行ごとにバラバラに並んだ1つのブロックになる。これを通常の
# 文章として折り返し・改行結合してしまうと、数値と単語が入り乱れた読めない
# 塊になる(改行こそが唯一のセル区切りの手がかりのため)。行の大部分が
# 純粋な数値であるブロックを「table_data」として検出し、書き込み時に
# 改行を保持したまま描画する(SPEC.md 8章の改行正規化の対象外とする)。
TABLE_DATA_MIN_LINES = 10
TABLE_DATA_NUMERIC_LINE_RATIO = 0.4
_NUMERIC_LINE_RE = re.compile(r"^-?\d+(\.\d+)?%?$")


def _looks_like_table_data(text: str) -> bool:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < TABLE_DATA_MIN_LINES:
        return False
    numeric_lines = sum(1 for line in lines if _NUMERIC_LINE_RE.match(line))
    return numeric_lines / len(lines) >= TABLE_DATA_NUMERIC_LINE_RATIO


def _looks_like_heading(text: str, font_size: float, body_font_median: float) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 80:
        return False
    if _SENTENCE_END_RE.search(stripped) and stripped.lower() not in _KNOWN_HEADINGS:
        return False
    if stripped.lower().rstrip(".:") in _KNOWN_HEADINGS:
        return True
    word_count = len(stripped.split())
    if word_count <= 8 and font_size >= body_font_median * 1.15:
        return True
    return False


def _classify_single(
    block: RawBlock,
    body_font_median: float,
    in_references: bool,
    is_first_page: bool,
    seen_heading: bool,
) -> str:
    text = block.text.strip()
    x0, y0, x1, y1 = block.rect

    # ヘッダ・フッタ(ページ上下端の短小ブロック)
    if len(text) < 80 and (y0 < HEADER_MARGIN or y1 > block.page_height - FOOTER_MARGIN):
        return "header_footer"

    if in_references:
        return "reference"

    # 見出しテキストが無く、いきなり "(1) ..." から始まる参考文献リスト
    if _REFERENCE_LIST_START_RE.match(text):
        return "reference_list_start"

    if _looks_like_heading(text, block.font_size, body_font_median):
        if text.strip().lower().rstrip(".:") in _REFERENCE_HEADINGS:
            return "reference_heading"
        return "heading"

    if _CAPTION_RE.match(text):
        return "caption"

    if _looks_like_table_data(text):
        return "table_data"

    if _looks_like_formula(text):
        return "formula"

    if is_first_page and not seen_heading:
        if "@" in text or _AFFIL_KEYWORDS.search(text):
            return "author_affil"

    if _FOOTNOTE_KEYWORDS.search(text):
        return "footnote"

    if len(text) >= MIN_BODY_CHARS and _SENTENCE_END_RE.search(text):
        return "body"

    if _looks_like_equation_fragment(text):
        return "equation"

    return "uncertain"


def classify_blocks(blocks: List[RawBlock]) -> List[str]:
    """ブロックのリスト(ページ順・読み順)を分類する。破壊的にblock.classificationも更新する。"""
    font_sizes = [b.font_size for b in blocks if b.text.strip()]
    body_font_median = statistics.median(font_sizes) if font_sizes else 10.0

    in_references = False
    seen_heading = False
    results: List[str] = []

    for block in blocks:
        cls = _classify_single(
            block,
            body_font_median=body_font_median,
            in_references=in_references,
            is_first_page=(block.page_index == 0),
            seen_heading=seen_heading,
        )
        if cls == "reference_heading":
            in_references = True
            cls = "heading"
        elif cls == "reference_list_start":
            in_references = True
            cls = "reference"
        if cls == "heading":
            seen_heading = True
        block.classification = cls
        results.append(cls)

    return results


# 翻訳対象から除外する分類(SPEC.md 3章の「除外」欄)
EXCLUDED_CLASSIFICATIONS = {"formula", "header_footer", "author_affil", "equation"}
# 既定では除外だが --translate-refs で翻訳対象に切り替え可能
REFERENCE_CLASSIFICATION = "reference"
