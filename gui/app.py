"""Fletアプリのエントリポイント。ライブラリ画面とリーダー画面を切り替える。

翻訳ロジックは実装しない。既存の core/pipeline.run_pipeline をバックグラウンド
スレッドで呼び出すだけ(gui/pipeline_runner.py)。
"""

import flet as ft

from gui import theme
from gui.blocks import count_issues_from_path
from gui.job_store import Job, load_jobs, save_jobs
from gui.library_view import build_library_view
from gui.new_translation_dialog import build_new_translation_dialog
from gui.pipeline_runner import run_job_in_background
from gui.reader_view import build_reader_view


class AppState:
    def __init__(self):
        self.jobs = load_jobs()
        self.selected_job_id = None


def main(page: ft.Page):
    page.title = "和訳作成"
    page.bgcolor = theme.BG
    page.padding = 0
    page.window.width = 1200
    page.window.height = 800

    state = AppState()
    content = ft.Container(expand=True, content=ft.Container())

    def find_job(job_id):
        return next((j for j in state.jobs if j.id == job_id), None)

    def show_library(e=None):
        state.selected_job_id = None
        content.content = build_library_view(state, on_open_job=show_reader, on_new_job=open_new_dialog)
        page.update()

    def show_reader(job_id=None):
        job_id = job_id or state.selected_job_id
        if job_id is None and state.jobs:
            job_id = state.jobs[0].id
        state.selected_job_id = job_id
        content.content = build_reader_view(find_job(job_id), on_back=show_library)
        page.update()

    def open_new_dialog(e=None):
        dlg = build_new_translation_dialog(page, state, on_job_created=on_job_created)
        page.open(dlg)

    def on_job_created(job: Job):
        state.jobs.insert(0, job)
        save_jobs(state.jobs)
        show_library()

        def on_complete(j: Job, report):
            j.status = "done"
            j.blocks_json_path = report.blocks_json_path
            j.compare_html_path = report.compare_html_path
            j.issue_count = count_issues_from_path(report.blocks_json_path)
            save_jobs(state.jobs)
            page.update()

        def on_error(j: Job, message: str):
            j.status = "error"
            j.error_message = message
            save_jobs(state.jobs)
            page.update()

        run_job_in_background(job, on_complete, on_error)

    sidebar = ft.Container(
        width=64,
        bgcolor=theme.SIDEBAR_BG,
        padding=ft.padding.only(top=16),
        content=ft.Column(
            [
                ft.IconButton(
                    icon=ft.Icons.MENU_BOOK_OUTLINED,
                    icon_color="white",
                    tooltip="リーダー",
                    on_click=lambda e: show_reader(),
                ),
                ft.IconButton(
                    icon=ft.Icons.FOLDER_COPY_OUTLINED,
                    icon_color="white",
                    tooltip="ライブラリ",
                    on_click=show_library,
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    page.add(
        ft.Row(
            [sidebar, ft.VerticalDivider(width=1, color=theme.BORDER), content],
            expand=True,
            spacing=0,
        )
    )

    show_library()


if __name__ == "__main__":
    ft.app(target=main)
