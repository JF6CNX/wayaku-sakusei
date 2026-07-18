"""「+ 新規翻訳」ダイアログ: PDF選択 + エンジン/分野選択 + ジョブ作成。"""

from pathlib import Path

import flet as ft

from core.glossary import VALID_FIELDS
from gui.job_store import Job, new_job_id, now_str


def build_new_translation_dialog(page: ft.Page, state, on_job_created) -> ft.AlertDialog:
    selected_path = {"value": None}
    filename_text = ft.Text("ファイルが選択されていません", size=13, color="#6b6b76")

    file_picker = ft.FilePicker()
    if file_picker not in page.overlay:
        page.overlay.append(file_picker)

    def on_pick_result(e: ft.FilePickerResultEvent):
        if e.files:
            selected_path["value"] = e.files[0].path
            filename_text.value = Path(e.files[0].path).name
            page.update()

    file_picker.on_result = on_pick_result

    engine_dropdown = ft.Dropdown(
        label="翻訳エンジン",
        value="claude",
        options=[ft.dropdown.Option(k) for k in ("claude", "deepl", "google")],
    )
    field_dropdown = ft.Dropdown(
        label="分野",
        value="general",
        options=[ft.dropdown.Option(f) for f in sorted(VALID_FIELDS)],
    )

    error_text = ft.Text("", color="#e0483e", size=12)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("新規翻訳"),
        content=ft.Column(
            [
                ft.ElevatedButton(
                    "PDFを選択",
                    icon=ft.Icons.UPLOAD_FILE,
                    on_click=lambda e: file_picker.pick_files(allowed_extensions=["pdf"]),
                ),
                filename_text,
                engine_dropdown,
                field_dropdown,
                error_text,
            ],
            tight=True,
            spacing=12,
        ),
        actions=[
            ft.TextButton("キャンセル", on_click=lambda e: page.close(dlg)),
            ft.FilledButton("開始", on_click=lambda e: _start(e)),
        ],
    )

    def _start(e):
        if not selected_path["value"]:
            error_text.value = "PDFファイルを選択してください"
            page.update()
            return

        input_path = selected_path["value"]
        output_path = str(Path("output") / (Path(input_path).stem + "_ja.pdf"))

        job = Job(
            id=new_job_id(),
            filename=Path(input_path).name,
            input_path=input_path,
            output_path=output_path,
            engine=engine_dropdown.value,
            field=field_dropdown.value,
            created_at=now_str(),
            status="running",
        )
        page.close(dlg)
        on_job_created(job)

    return dlg
