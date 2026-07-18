"""翻訳ジョブの永続化(app_data/jobs.json)。ライブラリ画面の一覧表示に使う。"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

APP_DATA_DIR = Path("app_data")
JOBS_FILE = APP_DATA_DIR / "jobs.json"


@dataclass
class Job:
    id: str
    filename: str
    input_path: str
    output_path: str
    engine: str
    field: str
    created_at: str
    status: str = "running"  # running / done / error
    error_message: Optional[str] = None
    issue_count: int = 0
    blocks_json_path: Optional[str] = None
    compare_html_path: Optional[str] = None
    report_path: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_app_data_dir() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_jobs() -> List[Job]:
    _ensure_app_data_dir()
    if not JOBS_FILE.exists():
        return []
    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Job(**item) for item in raw]


def save_jobs(jobs: List[Job]) -> None:
    _ensure_app_data_dir()
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump([j.to_dict() for j in jobs], f, ensure_ascii=False, indent=2)


def new_job_id() -> str:
    return uuid.uuid4().hex[:8]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
