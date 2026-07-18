"""<output>.blocks.json の読み込みと、リーダー画面の要確認タグ判定。"""

import json
from pathlib import Path
from typing import Dict, List

from core.classify import EXCLUDED_CLASSIFICATIONS

UNTRANSLATED_TAG = "(未翻訳)"
INCONSISTENCY_TAG = "用語一貫性の不一致"


def load_blocks(blocks_json_path: str) -> List[Dict]:
    with open(blocks_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def block_issue_tags(block: Dict) -> List[str]:
    tags = []
    if block["classification"] not in EXCLUDED_CLASSIFICATIONS and not block.get("translated_text"):
        tags.append(UNTRANSLATED_TAG)
    if any(str(flag).startswith("term_inconsistency:") for flag in block.get("flags", [])):
        tags.append(INCONSISTENCY_TAG)
    return tags


def count_issues(blocks: List[Dict]) -> int:
    return sum(1 for b in blocks if block_issue_tags(b))


def count_issues_from_path(blocks_json_path: str) -> int:
    if not blocks_json_path or not Path(blocks_json_path).exists():
        return 0
    return count_issues(load_blocks(blocks_json_path))
