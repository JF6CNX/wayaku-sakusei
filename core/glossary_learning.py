"""既に翻訳済みのブロック(原文/訳文ペア)から、新出の専門用語を用語集TSVに
取り込むための2段階ワークフロー。

AIモデルの学習(fine-tuning等)ではなく、翻訳時に使う訳語辞書(用語集TSV)への
追記であることに注意。翻訳品質そのものを底上げするのはあくまで用語集に載っている
単語の訳語統一のみで、文章全体の訳し直しではない。

1. export_learning_candidates: main.py --manual-file で作った(翻訳済みの)
   JSONファイルを読み込み、原文/訳文ペアと「候補語(candidate_terms)」の
   空リストを持つファイルを書き出す。
2. (人手 or この会話でのClaudeによる直接作業で) 各ペアを見て、専門用語の
   英語→日本語の対応を candidate_terms に埋める。
3. import_learned_terms: 埋まったファイルを読み込み、用語集TSVにマージする。
   既存のエントリと訳語が矛盾する場合は上書きせず、conflicts として報告する。
"""

import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Dict, List, Optional

from core.glossary import GlossaryEntry, load_tsv

LEARNING_INSTRUCTIONS = (
    "各ペアの original_text(英語)と translated_text(日本語)を見比べて、"
    "その分野の専門用語・定訳として辞書に登録する価値がある英語→日本語の対応だけを"
    "candidate_terms に追加してください。各エントリは "
    '{"en": "英語表現", "ja": "日本語訳", "note": "補足(任意)"} の形式です。'
    "一般的な英単語(the, and, resultsなど)や、文全体・長い一節は登録しないでください。"
    "略語(NMR, DFT等)や化学式など、protect.pyで既に保護される表記は登録不要です。"
)


@dataclass
class ImportResult:
    added: List[GlossaryEntry] = dataclass_field(default_factory=list)
    skipped_duplicates: List[str] = dataclass_field(default_factory=list)
    conflicts: List[dict] = dataclass_field(default_factory=list)


def export_learning_candidates(source_path: Path, output_path: Path) -> int:
    """翻訳済みJSON(--manual-file で作ったもの)から候補抽出用ファイルを書き出す。

    Returns:
        書き出したペア数
    """
    with open(source_path, "r", encoding="utf-8") as f:
        source = json.load(f)

    pairs = []
    for block in source.get("blocks", []):
        translated = block.get("translated_text")
        if not translated:
            continue
        pairs.append(
            {
                "block_id": block.get("block_id"),
                "original_text": block.get("original_text"),
                "translated_text": translated,
                "candidate_terms": [],
            }
        )

    payload = {"instructions": LEARNING_INSTRUCTIONS, "pairs": pairs}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return len(pairs)


def _load_existing_glossary_map(glossary_tsv_path: Path) -> Dict[str, GlossaryEntry]:
    if not glossary_tsv_path.exists():
        return {}
    entries = load_tsv(glossary_tsv_path)
    return {e.en.lower(): e for e in entries}


def _write_glossary_tsv(glossary_tsv_path: Path, entries: List[GlossaryEntry]) -> None:
    glossary_tsv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(glossary_tsv_path, "w", encoding="utf-8") as f:
        f.write("en\tja\tnote\n")
        for entry in sorted(entries, key=lambda e: e.en.lower()):
            note = entry.note.replace("\t", " ") if entry.note else ""
            f.write(f"{entry.en}\t{entry.ja}\t{note}\n")


def import_learned_terms(filled_path: Path, glossary_tsv_path: Path) -> ImportResult:
    """候補抽出ファイル(candidate_termsを埋めたもの)を用語集TSVにマージする。

    既存の用語(英語表現が同じ、大文字小文字は無視)がすでに別の訳語で
    登録されている場合は上書きせず、conflicts に記録して手動確認に回す。
    """
    with open(filled_path, "r", encoding="utf-8") as f:
        filled = json.load(f)

    existing = _load_existing_glossary_map(glossary_tsv_path)
    result = ImportResult()

    seen_in_this_run: Dict[str, GlossaryEntry] = {}
    conflicted_keys = set()

    for pair in filled.get("pairs", []):
        for term in pair.get("candidate_terms", []):
            en = (term.get("en") or "").strip()
            ja = (term.get("ja") or "").strip()
            note = (term.get("note") or "").strip()
            if not en or not ja:
                continue

            key = en.lower()
            new_entry = GlossaryEntry(en=en, ja=ja, note=note)

            if key in existing:
                if existing[key].ja != ja:
                    result.conflicts.append(
                        {"en": en, "existing_ja": existing[key].ja, "new_ja": ja}
                    )
                else:
                    result.skipped_duplicates.append(en)
                continue

            if key in seen_in_this_run and seen_in_this_run[key].ja != ja:
                conflicted_keys.add(key)
                result.conflicts.append(
                    {"en": en, "existing_ja": seen_in_this_run[key].ja, "new_ja": ja}
                )
                continue

            seen_in_this_run[key] = new_entry

    for key in conflicted_keys:
        seen_in_this_run.pop(key, None)

    if seen_in_this_run:
        result.added = list(seen_in_this_run.values())
        merged = list(existing.values()) + result.added
        _write_glossary_tsv(glossary_tsv_path, merged)

    return result
