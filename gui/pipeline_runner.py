"""既存のcore.pipeline.run_pipelineをバックグラウンドスレッドで実行するラッパー。

翻訳ロジック自体は再実装せず、CLI (main.py) と同じ core/ パイプラインを呼び出す。
"""

import threading
from typing import Callable

from core.glossary import build_glossary
from core.pipeline import run_pipeline
from main import load_config
from translators import get_translator


def run_job_in_background(job, on_complete: Callable, on_error: Callable) -> threading.Thread:
    def _worker():
        try:
            config = load_config()
            glossary = build_glossary(field=job.field)
            translator = get_translator(
                job.engine,
                field=job.field,
                source_lang=config["translation"]["source_lang"],
                target_lang=config["translation"]["target_lang"],
            )
            report = run_pipeline(
                input_path=job.input_path,
                output_path=job.output_path,
                translator=translator,
                glossary=glossary,
                font_path=config["font"]["path"],
                default_size=config["font"]["default_size"],
                min_size=config["font"]["min_size"],
                batch_size=config["translation"]["batch_size"],
                overflow_strategy=config["layout"]["overflow_strategy"],
            )
            on_complete(job, report)
        except Exception as e:  # noqa: BLE001 - バックグラウンドスレッドなのでUIにエラー内容を伝える
            on_error(job, str(e))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
