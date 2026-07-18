"""fitz(PyMuPDF)を使ったPDFの抽出・書き込み(SPEC.md 8章)。

- extract_blocks: ページごとにテキストブロック(座標・フォントサイズ・太字トークン)を抽出
- write_translations: 原文ブロックを白塗りで消去し、同じ矩形に日本語訳を描画
"""

import re
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from core.classify import RawBlock

_WHITESPACE_RUN_RE = re.compile(r"\s*\n\s*")


def _normalize_for_layout(text: str) -> str:
    """描画直前に改行を空白へ変換し、矩形の幅に応じた自然な折り返しに任せる。

    抽出時の "\\n" は原文(英語)の行送り位置を反映しているだけで、訳文にとって
    理想的な折り返し位置とは限らない。強制改行をそのまま残すと、横長で低い
    矩形(例: 横並びのUIバー)では訳文が意味なく縦に積み上がってしまい、
    本来なら十分収まる幅があっても収まらなくなることがある。

    ただし見出し記号「■」の直前の改行だけは、段落と見出しを分けるための
    意図的な区切りとして保持する。
    """

    def _repl(match: "re.Match") -> str:
        tail = text[match.end() : match.end() + 1]
        return "\n" if tail == "■" else " "

    return _WHITESPACE_RUN_RE.sub(_repl, text).strip()

MIN_BLOCK_CHARS = 3
BOLD_FLAG = 1 << 4  # PyMuPDF span flags: bit4 = bold

# fitzのブロック検出は、余白の少ない全幅要素(要旨ボックス等)と、その直後に続く
# 段組み本文を1つのブロックに誤って結合することがある。結合されたブロックの
# bboxは全幅のまま(=元の全幅の右端x1を引きずる)になり、redaction時に
# 隣のカラムの本文まで白塗りして上書きしてしまう。
# 行の右端(x1)が大きく・持続的に狭くなった箇所で1ブロックを分割することで、
# この「段組み跨ぎ」を防ぐ。
COLUMN_SPLIT_THRESHOLD = 60.0  # pt: これ以上x1が狭くなったら段組み変化とみなす
COLUMN_SPLIT_CONFIRM_TOLERANCE = 20.0  # pt: 次の行も同程度の幅なら「持続的」と確認


def _split_lines_by_column_width(lines: List[dict]) -> List[List[dict]]:
    """1つのfitzブロック内の行を、段組み幅が持続的に変化した箇所で分割する。"""
    if not lines:
        return []

    groups: List[List[dict]] = [[lines[0]]]

    for i in range(1, len(lines)):
        line = lines[i]
        current_group = groups[-1]
        group_max_x1 = max(l["bbox"][2] for l in current_group)
        is_last_line = i == len(lines) - 1
        narrowed = group_max_x1 - line["bbox"][2] > COLUMN_SPLIT_THRESHOLD

        if narrowed and not is_last_line:
            next_line = lines[i + 1]
            sustained = abs(next_line["bbox"][2] - line["bbox"][2]) < COLUMN_SPLIT_CONFIRM_TOLERANCE
            if sustained:
                groups.append([line])
                continue

        current_group.append(line)

    return groups


# 行末で単語がハイフン+改行によって分割されている場合(例: "organo-\nmetallic")、
# そのまま翻訳エンジンに渡すと単語が分断されて誤訳・混乱の原因になる。
# ハイフンの前後が共に小文字であれば、行送りによる分割とみなして結合する。
# (大文字が続く場合は新しい文・固有名詞である可能性が高いため結合しない)
_HYPHENATED_LINE_BREAK_RE = re.compile(r"([a-z])-\n([a-z])")


def _dehyphenate(text: str) -> str:
    return _HYPHENATED_LINE_BREAK_RE.sub(r"\1\2", text)


def _bold_ratio_and_tokens(lines: List[dict]) -> Tuple[float, List[str]]:
    total_chars = 0
    bold_chars = 0
    bold_tokens: List[str] = []
    for line in lines:
        for span in line["spans"]:
            text = span["text"]
            total_chars += len(text)
            if span.get("flags", 0) & BOLD_FLAG:
                bold_chars += len(text)
                bold_tokens.extend(t for t in text.split() if t)
    ratio = bold_chars / total_chars if total_chars else 0.0
    return ratio, bold_tokens


def extract_blocks(doc: fitz.Document) -> List[RawBlock]:
    blocks: List[RawBlock] = []
    for page_index, page in enumerate(doc):
        page_height = page.rect.height
        raw = page.get_text("dict")
        for block in raw["blocks"]:
            if block.get("type") != 0:  # 0 = テキスト, 1 = 画像
                continue

            for line_group in _split_lines_by_column_width(block["lines"]):
                lines_text = []
                font_sizes = []
                x0s, y0s, x1s, y1s = [], [], [], []
                for line in line_group:
                    spans_text = "".join(span["text"] for span in line["spans"])
                    if spans_text.strip():
                        lines_text.append(spans_text)
                    font_sizes.extend(span["size"] for span in line["spans"])
                    lx0, ly0, lx1, ly1 = line["bbox"]
                    x0s.append(lx0)
                    y0s.append(ly0)
                    x1s.append(lx1)
                    y1s.append(ly1)

                text = _dehyphenate("\n".join(lines_text).strip())
                if len(text) < MIN_BLOCK_CHARS:
                    continue

                bold_ratio, bold_tokens = _bold_ratio_and_tokens(line_group)

                blocks.append(
                    RawBlock(
                        page_index=page_index,
                        rect=(min(x0s), min(y0s), max(x1s), max(y1s)),
                        text=text,
                        font_size=(sum(font_sizes) / len(font_sizes)) if font_sizes else 10.0,
                        page_height=page_height,
                        bold_ratio=bold_ratio,
                        bold_tokens=bold_tokens if bold_ratio > 0 else [],
                    )
                )
    return blocks


MAX_RECT_EXPANSION = 1.3  # 矩形拡張は元の高さの130%まで(SPEC.md 8章)
PAGE_BOTTOM_MARGIN = 20.0
GROW_STEP = 0.25
GROW_CAP_RATIO = 1.3  # 元のフォントサイズの130%までしか拡大しない
TEXT_ALIGN = fitz.TEXT_ALIGN_JUSTIFY  # 各行の右端を揃え、行内の隙間を減らす


def _search_best_fit(
    page: "fitz.Page",
    rect: fitz.Rect,
    translated_text: str,
    font_name: str,
    base_size: float,
    min_size: float,
    max_size: float,
) -> Optional[float]:
    """rect に収まる中で最も大きい(=余白が少ない)フォントサイズを探す。

    まず base_size から縮小して「収まる」サイズを見つけ、次にそこから
    max_size まで少しずつ拡大して、矩形の余白(隙間)をできるだけ埋める。
    見つからない場合は None。
    """
    size = base_size
    fit_size: Optional[float] = None
    while size >= min_size:
        rc = page.insert_textbox(
            rect,
            translated_text,
            fontname=font_name,
            fontsize=size,
            align=TEXT_ALIGN,
            render_mode=3,  # invisible: レイアウト確認のみで実際には描画しない
        )
        if rc >= 0:
            fit_size = size
            break
        size -= 0.5

    if fit_size is None:
        return None

    grown = fit_size
    candidate = fit_size + GROW_STEP
    while candidate <= max_size:
        rc = page.insert_textbox(
            rect,
            translated_text,
            fontname=font_name,
            fontsize=candidate,
            align=TEXT_ALIGN,
            render_mode=3,
        )
        if rc < 0:
            break
        grown = candidate
        candidate += GROW_STEP

    return grown


def _find_fitting_layout(
    page: "fitz.Page",
    rect: fitz.Rect,
    translated_text: str,
    font_name: str,
    default_size: float,
    min_size: float,
    overflow_strategy: str,
    max_y1: Optional[float] = None,
) -> Optional[Tuple[fitz.Rect, float]]:
    """収まる中で最も余白の少ない (矩形, フォントサイズ) を探す。

    max_y1 が指定された場合、矩形拡張はそこまでしか行わない(同じ列にある
    次のブロック — 数式や別の段落など — の領域まで食い込むのを防ぐため)。

    見つからない場合は None を返す(呼び出し側は原文を消さずに残す)。
    """
    max_size = default_size * GROW_CAP_RATIO
    size = _search_best_fit(page, rect, translated_text, font_name, default_size, min_size, max_size)
    if size is not None:
        return rect, size

    if overflow_strategy != "shrink":
        return None

    # フォント縮小でも収まらない場合、矩形を下方向に拡張して再試行(一度だけ)
    expansion_limit = page.rect.height - PAGE_BOTTOM_MARGIN
    if max_y1 is not None:
        expansion_limit = min(expansion_limit, max_y1)

    expanded_height = rect.height * MAX_RECT_EXPANSION
    expanded_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + expanded_height)
    if expanded_rect.y1 > expansion_limit:
        expanded_rect.y1 = expansion_limit
    if expanded_rect.height <= rect.height:
        return None

    size = _search_best_fit(
        page, expanded_rect, translated_text, font_name, default_size, min_size, max_size
    )
    if size is not None:
        return expanded_rect, size

    return None


def _rects_overlap(r1: fitz.Rect, r2: fitz.Rect) -> bool:
    return r1.x0 < r2.x1 and r2.x0 < r1.x1 and r1.y0 < r2.y1 and r2.y0 < r1.y1


def _group_overlapping_indices(indices: List[int], blocks: List[RawBlock]) -> List[List[int]]:
    """矩形が重なっているブロック同士を1つのグループにまとめる(推移的に連結)。

    密に組版された数式周辺では、原文の抽出段階ですでに隣接ブロックの矩形が
    重なっていることがある(例: 1つの長いブロックの末尾行が、次のブロックの
    先頭行と同じ高さまで垂れ込む)。これらを別々に白塗り・描画すると、
    訳文同士が重なって表示されてしまうため、重なりのあるブロックはまとめて
    1つの矩形・1つのテキストとして扱う。
    """
    groups: List[List[int]] = []
    for i in sorted(indices, key=lambda idx: blocks[idx].rect[1]):
        rect_i = fitz.Rect(blocks[i].rect)
        target_group = None
        for group in groups:
            if any(_rects_overlap(rect_i, fitz.Rect(blocks[j].rect)) for j in group):
                target_group = group
                break
        if target_group is None:
            groups.append([i])
        else:
            target_group.append(i)
    return groups


def write_translations(
    doc: fitz.Document,
    blocks: List[RawBlock],
    final_texts: List[Optional[str]],
    font_path: str,
    default_size: float = 10.0,
    min_size: float = 6.0,
    overflow_strategy: str = "shrink",
) -> List[str]:
    """各ブロックへの書き込み結果を返す。

    final_texts[i] が None のブロックは "skipped"。
    収まらず書き込めなかった場合は "overflow"(原文のまま残る)。
    正常に書き込めた場合は "written"。

    各ブロックの基準フォントサイズは、config一律の default_size ではなく
    そのブロックの元のフォントサイズ(block.font_size)を優先する。
    見出しなど元々大きい文字が、一律に小さく描画されて余白が残るのを防ぐため。

    実装上の注意: フォントサイズ探索(_find_fitting_layout)は render_mode=3 の
    「不可視」描画で行うが、これも実際にはページの内容ストリームに書き込みが
    発生する。ブロックごとに何度も繰り返すと、本番ページに大量の不可視テキストが
    蓄積し、apply_redactions() のたびに行うフォント再埋め込みと相まって、
    無関係な既存テキスト(元のACSフォントのグリフ)の位置がずれる不具合が
    確認された。これを避けるため、探索は使い捨てのスクラッチページ上で行い、
    本番ページには「白塗りを1ページ分まとめて1回だけ適用→フォント再埋め込みも
    1回だけ→実際の描画」という最小限の操作のみを行う。
    """
    font_name = "japanese-font"
    status: List[Optional[str]] = [None] * len(blocks)

    pages_to_indices: Dict[int, List[int]] = {}
    for i, text in enumerate(final_texts):
        if text is None:
            status[i] = "skipped"
            continue
        pages_to_indices.setdefault(blocks[i].page_index, []).append(i)

    for page_index, indices in pages_to_indices.items():
        page = doc[page_index]

        # このページの全ブロック(翻訳対象外・数式なども含む)。矩形拡張が
        # 他のブロックの領域まで食い込まないようにする上限計算に使う。
        all_page_rects = [fitz.Rect(b.rect) for b in blocks if b.page_index == page_index]

        scratch_doc = fitz.open()
        scratch_page = scratch_doc.new_page(width=page.rect.width, height=page.rect.height)
        scratch_page.insert_font(fontname=font_name, fontfile=font_path)

        groups = _group_overlapping_indices(indices, blocks)

        group_layouts: List[Tuple[List[int], fitz.Rect, float, str]] = []
        for group in groups:
            group_sorted = sorted(group)  # 元の読み順(抽出順)を保つ
            member_rects = [fitz.Rect(blocks[i].rect) for i in group_sorted]
            merged_rect = member_rects[0]
            for r in member_rects[1:]:
                merged_rect |= r

            is_table_data = any(blocks[i].classification == "table_data" for i in group_sorted)
            if is_table_data:
                # 表データは改行こそが唯一の行区切りの手がかりなので、
                # 折り返し用の改行正規化(空白への変換)を行わずそのまま使う。
                merged_text = "\n".join(final_texts[i] for i in group_sorted)
            else:
                merged_text = _normalize_for_layout(
                    " ".join(final_texts[i] for i in group_sorted)
                )
            base_size = max(
                (blocks[i].font_size for i in group_sorted if blocks[i].font_size and blocks[i].font_size > 0),
                default=default_size,
            )

            # 同じ列(x範囲が重なる)で、このグループより下にある最も近いブロックの
            # 上端を、矩形拡張がそこを超えないようにする上限とする
            candidate_y1s = [
                r.y0
                for r in all_page_rects
                if r.y0 >= merged_rect.y1
                and r.x0 < merged_rect.x1
                and merged_rect.x0 < r.x1
            ]
            max_y1 = min(candidate_y1s) if candidate_y1s else None

            layout = _find_fitting_layout(
                scratch_page,
                merged_rect,
                merged_text,
                font_name,
                base_size,
                min_size,
                overflow_strategy,
                max_y1=max_y1,
            )
            if layout is None:
                for i in group_sorted:
                    status[i] = "overflow"
            else:
                rect, size = layout
                group_layouts.append((group_sorted, rect, size, merged_text))

        scratch_doc.close()

        if not group_layouts:
            continue

        page.insert_font(fontname=font_name, fontfile=font_path)
        for _group, rect, _size, _text in group_layouts:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        # apply_redactions() はページのフォントリソースを消してしまうため再埋め込みが必要
        page.insert_font(fontname=font_name, fontfile=font_path)

        for group_sorted, rect, size, merged_text in group_layouts:
            page.insert_textbox(
                rect,
                merged_text,
                fontname=font_name,
                fontsize=size,
                align=TEXT_ALIGN,
            )
            for i in group_sorted:
                status[i] = "written"

    return status
