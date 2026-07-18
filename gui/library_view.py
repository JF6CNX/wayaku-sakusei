"""ライブラリ画面: 新規翻訳ボタン + 過去の翻訳ジョブ一覧(要確認バッジ付き)。"""

import flet as ft

from gui import theme


def _job_card(job, on_open_job) -> ft.Control:
    status_control = None
    badge = None

    if job.status == "running":
        status_control = ft.Row(
            [
                ft.ProgressRing(width=14, height=14, stroke_width=2),
                ft.Text("実行中", size=12, color=theme.TEXT_SECONDARY),
            ],
            spacing=6,
        )
    elif job.status == "error":
        status_control = ft.Text("エラー", size=12, color=theme.UNTRANSLATED_COLOR)
    elif job.issue_count > 0:
        badge = ft.Container(
            content=ft.Text(f"要確認 {job.issue_count}件", size=12, color=theme.BADGE_TEXT),
            bgcolor=theme.BADGE_BG,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=12,
        )

    engine_label = {"claude": "Claude API", "deepl": "DeepL API", "google": "Google Translate API"}.get(
        job.engine, job.engine
    )

    left_column = ft.Column(
        [
            ft.Text(job.filename, size=15, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
            ft.Text(f"{engine_label} · {job.created_at}", size=12, color=theme.TEXT_SECONDARY),
        ],
        spacing=2,
        expand=True,
    )

    row_children = [left_column]
    if status_control is not None:
        row_children.append(status_control)
    if badge is not None:
        row_children.append(badge)

    is_clickable = job.status == "done"

    return ft.Container(
        content=ft.Row(row_children, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=16,
        bgcolor=theme.CARD_BG,
        border=ft.border.all(1, theme.BORDER),
        border_radius=10,
        on_click=(lambda e: on_open_job(job.id)) if is_clickable else None,
        ink=is_clickable,
    )


def build_library_view(state, on_open_job, on_new_job) -> ft.Control:
    cards = [_job_card(job, on_open_job) for job in state.jobs]

    if not cards:
        body: ft.Control = ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            content=ft.Text("まだ翻訳ジョブがありません。「+ 新規翻訳」から始めてください。", color=theme.TEXT_SECONDARY),
        )
    else:
        body = ft.ListView(controls=cards, spacing=10, expand=True)

    return ft.Container(
        padding=24,
        expand=True,
        bgcolor=theme.BG,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("ライブラリ", size=20, weight=ft.FontWeight.BOLD, color=theme.TEXT_PRIMARY),
                        ft.ElevatedButton(
                            "+ 新規翻訳",
                            on_click=on_new_job,
                            bgcolor=theme.ACCENT,
                            color="white",
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                body,
            ],
            expand=True,
            spacing=16,
        ),
    )
