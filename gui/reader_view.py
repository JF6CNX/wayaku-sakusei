"""リーダー画面: 原文/対訳/和訳タブ + インライン要確認タグ表示。"""

import flet as ft

from gui import theme
from gui.blocks import INCONSISTENCY_TAG, UNTRANSLATED_TAG, block_issue_tags, load_blocks

_TAG_COLORS = {
    UNTRANSLATED_TAG: theme.UNTRANSLATED_COLOR,
    INCONSISTENCY_TAG: theme.INCONSISTENCY_COLOR,
}


def _tag_spans(tags):
    spans = []
    for tag in tags:
        color = _TAG_COLORS.get(tag, theme.INCONSISTENCY_COLOR)
        spans.append(ft.TextSpan("  "))
        spans.append(
            ft.TextSpan(
                tag,
                ft.TextStyle(
                    color=color,
                    decoration=ft.TextDecoration.UNDERLINE,
                    decoration_color=color,
                ),
            )
        )
    return spans


def _paragraph_text(body: str, tags, size: int, bold: bool) -> ft.Text:
    spans = [ft.TextSpan(body)] + _tag_spans(tags)
    return ft.Text(
        spans=spans,
        size=size,
        weight=ft.FontWeight.BOLD if bold else None,
        color=theme.TEXT_PRIMARY,
    )


def _build_flow(blocks, mode: str) -> ft.ListView:
    lv = ft.ListView(expand=True, spacing=14, padding=24, auto_scroll=False)
    current_page = None
    for b in blocks:
        if b["classification"] == "header_footer":
            continue

        if current_page != b["page_index"]:
            current_page = b["page_index"]
            lv.controls.append(
                ft.Text(f"— p.{current_page + 1} —", size=11, color=theme.TEXT_SECONDARY)
            )

        is_heading = b["classification"] == "heading"
        tags = block_issue_tags(b)

        if mode == "original":
            lv.controls.append(_paragraph_text(b["original_text"], [], 15 if is_heading else 14, is_heading))
        elif mode == "ja":
            body = b["translated_text"] or b["original_text"]
            lv.controls.append(_paragraph_text(body, tags, 15 if is_heading else 14, is_heading))
        else:  # 対訳(compare): 原文を薄く上に、訳文を下に並べる
            lv.controls.append(
                ft.Text(
                    b["original_text"],
                    size=13,
                    color=theme.TEXT_SECONDARY,
                    weight=ft.FontWeight.BOLD if is_heading else None,
                )
            )
            body = b["translated_text"] or ""
            lv.controls.append(_paragraph_text(body, tags, 15 if is_heading else 14, is_heading))
    return lv


def build_reader_view(job, on_back) -> ft.Control:
    if job is None:
        return ft.Container(padding=24, content=ft.Text("翻訳ジョブが選択されていません"))

    header = ft.Row(
        [
            ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_back(), tooltip="ライブラリへ戻る"),
            ft.Text(job.filename, size=18, weight=ft.FontWeight.BOLD, expand=True),
        ]
    )

    if job.status == "running":
        return ft.Container(
            padding=24,
            content=ft.Column(
                [
                    header,
                    ft.Row([ft.ProgressRing(), ft.Text("翻訳中です…")]),
                ],
                spacing=20,
            ),
        )

    if job.status == "error":
        return ft.Container(
            padding=24,
            content=ft.Column(
                [
                    header,
                    ft.Text(
                        f"エラーが発生しました: {job.error_message}",
                        color=theme.UNTRANSLATED_COLOR,
                    ),
                ],
                spacing=20,
            ),
        )

    blocks = load_blocks(job.blocks_json_path)

    tabs = ft.Tabs(
        selected_index=2,
        tabs=[
            ft.Tab(text="原文", content=_build_flow(blocks, "original")),
            ft.Tab(text="対訳", content=_build_flow(blocks, "compare")),
            ft.Tab(text="和訳", content=_build_flow(blocks, "ja")),
        ],
        expand=True,
    )

    return ft.Column(
        [
            ft.Container(padding=ft.padding.symmetric(horizontal=20, vertical=12), content=header),
            tabs,
        ],
        expand=True,
        spacing=0,
    )
