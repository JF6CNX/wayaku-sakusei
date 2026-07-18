"""翻訳パイプライン全体のオーケストレーション(SPEC.md 全体の統合)。

抽出 → 分類 → 化学用語保護 → 用語集ヒント抽出 → 翻訳 → 検証 → 復元 → PDF書き込み
→ report.json / review-tsv 出力、までを行う。
"""

import csv
import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Dict, List, Optional

import fitz

from core.classify import EXCLUDED_CLASSIFICATIONS, RawBlock, classify_blocks
from core.compare_html import build_comparison_html
from core.consistency import check_glossary_consistency
from core.glossary import Glossary, GlossaryEntry, build_glossary
from core.pdf_io import extract_blocks, write_translations
from core.protect import protect_text, restore_text
from core.validate import ValidationResult, validate_translation
from translators.base import BaseTranslator


@dataclass
class BlockResult:
    page_index: int
    classification: str
    original_text: str
    translated_text: Optional[str] = None
    flags: List[str] = dataclass_field(default_factory=list)
    written: bool = False


@dataclass
class PipelineReport:
    input_path: str
    output_path: str
    total_blocks: int = 0
    translated_blocks: int = 0
    skipped_by_classification: Dict[str, int] = dataclass_field(default_factory=dict)
    failed_validation: List[dict] = dataclass_field(default_factory=list)
    layout_overflow: List[dict] = dataclass_field(default_factory=list)
    glossary_terms_used: List[str] = dataclass_field(default_factory=list)
    manual_export_path: Optional[str] = None
    compare_html_path: Optional[str] = None
    blocks_json_path: Optional[str] = None
    glossary_inconsistencies: List[dict] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "input": self.input_path,
            "output": self.output_path,
            "total_blocks": self.total_blocks,
            "translated_blocks": self.translated_blocks,
            "skipped_by_classification": self.skipped_by_classification,
            "failed_validation": self.failed_validation,
            "layout_overflow": self.layout_overflow,
            "glossary_inconsistencies": self.glossary_inconsistencies,
            "glossary_terms_used": sorted(set(self.glossary_terms_used)),
        }


MANUAL_TRANSLATION_INSTRUCTIONS = (
    "各ブロックの protected_text を自然な日本語の学術文体(である調)に翻訳し、"
    "translated_text フィールドに書き込んでください。"
    "⟦CHEM_nnn⟧ 形式のプレースホルダは化学式・単位付き数値・スペクトルデータ等を"
    "保護しているため、削除・改変・翻訳せずそのまま出力に残してください。"
    "glossary_hints にある用語は指定の訳語を優先してください。"
    "翻訳しない(原文のまま残す)場合は translated_text を null のままにしてください。"
    "classification が table_data のブロックは、罫線の無い表のセルが行ごとに"
    "バラバラに並んだものです(改行こそが唯一のセル区切り)。行数と行の並び順を"
    "一切変えず、数値のみの行はそのまま(訳さず)残し、文字のラベル行だけを"
    "日本語に訳してください。行を増減させたり、複数行を1行にまとめたりしないこと。"
    "隣接するブロックは、PDFの段組みの都合で1つの文・段落が分割されたもの"
    "であることがあります。ある block の original_text が句点なしで終わって"
    "いる場合、次の block はその続きの可能性が高いです。同じ動詞の活用語尾"
    "(例:「〜を示し、」の直後に「〜を示し、」)を続けて繰り返すなど不自然な"
    "重複を避け、ブロックをまたいでも自然につながる訳文にしてください。"
)


def _extract_context(blocks: List[RawBlock]) -> Optional[str]:
    """タイトル・要旨らしきテキストを取得し、訳語一貫性のための文脈として使う(簡易版)。"""
    page0_blocks = [b for b in blocks if b.page_index == 0]
    if not page0_blocks:
        return None

    title = page0_blocks[0].text.strip()

    abstract_parts: List[str] = []
    in_abstract = False
    for b in page0_blocks:
        stripped = b.text.strip().lower().rstrip(".:")
        if b.classification == "heading" and stripped == "abstract":
            in_abstract = True
            continue
        if b.classification == "heading" and in_abstract:
            break
        if in_abstract and b.classification == "body":
            abstract_parts.append(b.text.strip())

    abstract = " ".join(abstract_parts)
    if not abstract:
        # Abstract見出しが見つからない場合、最初の本文ブロックで代用
        body_blocks = [b for b in page0_blocks if b.classification == "body"]
        if body_blocks:
            abstract = body_blocks[0].text.strip()

    context = f"タイトル(推定): {title}"
    if abstract:
        context += f"\n要旨(推定): {abstract[:800]}"
    return context


def _chunked(items: List, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _export_manual_translation_file(
    path: Path,
    target_blocks: List[RawBlock],
    to_translate_indices: List[int],
    glossary: Glossary,
    context: Optional[str],
) -> None:
    blocks_payload = []
    for idx in to_translate_indices:
        block = target_blocks[idx]
        protected_text, _ = protect_text(block.text, bold_tokens=block.bold_tokens)
        glossary_hints = glossary.get_relevant_terms(protected_text)
        blocks_payload.append(
            {
                "block_id": idx,
                "page": block.page_index + 1,
                "classification": block.classification,
                "original_text": block.text,
                "protected_text": protected_text,
                "glossary_hints": [
                    {"en": e.en, "ja": e.ja, "note": e.note} for e in glossary_hints
                ],
                "translated_text": None,
            }
        )

    payload = {
        "instructions": MANUAL_TRANSLATION_INSTRUCTIONS,
        "context": context,
        "blocks": blocks_payload,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_manual_translations(path: Path, target_blocks: List[RawBlock]) -> Dict[int, Optional[str]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    translations: Dict[int, Optional[str]] = {}
    for entry in payload.get("blocks", []):
        block_id = entry["block_id"]
        if block_id >= len(target_blocks):
            raise ValueError(
                f"翻訳ファイルの block_id={block_id} がPDFのブロック数を超えています。"
                "PDFやページ指定が変わっていないか確認し、再度エクスポートし直してください。"
            )
        current_text = target_blocks[block_id].text
        if entry.get("original_text") != current_text:
            raise ValueError(
                f"翻訳ファイルの block_id={block_id} の原文が現在のPDF抽出結果と一致しません。"
                "PDFや--pages指定が変わった可能性があります。再度エクスポートし直してください。"
            )
        translations[block_id] = entry.get("translated_text")
    return translations


def run_pipeline(
    input_path: str,
    output_path: str,
    translator: Optional[BaseTranslator],
    glossary: Optional[Glossary] = None,
    font_path: str = "fonts/NotoSansJP-Regular.ttf",
    default_size: float = 10.0,
    min_size: float = 6.0,
    batch_size: int = 10,
    overflow_strategy: str = "shrink",
    translate_refs: bool = False,
    pages: Optional[List[int]] = None,
    dry_run: bool = False,
    review_tsv_path: Optional[str] = None,
    password: Optional[str] = None,
    manual_translation_path: Optional[str] = None,
) -> PipelineReport:
    """
    manual_translation_path が指定された場合、APIを使う翻訳エンジンの代わりに
    人手(またはこの会話でのClaudeによる直接翻訳)でJSONファイルに書き込んだ
    訳文を使う。ファイルが存在しなければ翻訳待ちブロックをエクスポートして終了し、
    存在すればそこから訳文を読み込んで通常通り検証・書き込みを行う。
    """
    if glossary is None:
        glossary = build_glossary()

    # 翻訳待ちブロックをエクスポートするだけの場合はPDFに書き込まないのでフォント不要
    export_only = bool(manual_translation_path) and not Path(manual_translation_path).exists()

    if not dry_run and not export_only and not Path(font_path).exists():
        raise FileNotFoundError(
            f"日本語フォントが見つかりません: {font_path}\n"
            "Noto Sans JP 等のTTFファイルを配置してください。"
        )

    doc = fitz.open(input_path)
    if doc.is_encrypted:
        if not password or not doc.authenticate(password):
            raise ValueError("PDFが暗号化されています。--password で正しいパスワードを指定してください。")

    all_blocks = extract_blocks(doc)
    classify_blocks(all_blocks)

    if pages:
        page_set = set(p - 1 for p in pages)  # 1-indexed -> 0-indexed
        target_blocks = [b for b in all_blocks if b.page_index in page_set]
    else:
        target_blocks = all_blocks

    report = PipelineReport(input_path=input_path, output_path=output_path)
    report.total_blocks = len(target_blocks)

    context = _extract_context(all_blocks)

    results: List[BlockResult] = []
    to_translate_indices: List[int] = []

    for idx, block in enumerate(target_blocks):
        cls = block.classification or "uncertain"
        is_reference = cls == "reference"
        excluded = cls in EXCLUDED_CLASSIFICATIONS or (is_reference and not translate_refs)

        results.append(
            BlockResult(page_index=block.page_index, classification=cls, original_text=block.text)
        )
        if excluded:
            report.skipped_by_classification[cls] = report.skipped_by_classification.get(cls, 0) + 1
        else:
            to_translate_indices.append(idx)

    if dry_run:
        doc.close()
        return report

    if manual_translation_path:
        manual_path = Path(manual_translation_path)
        if not manual_path.exists():
            _export_manual_translation_file(manual_path, target_blocks, to_translate_indices, glossary, context)
            report.manual_export_path = str(manual_path)
            doc.close()
            return report

        manual_translations = _load_manual_translations(manual_path, target_blocks)
        all_target_text = "\n".join(target_blocks[i].text for i in to_translate_indices)
        report.glossary_terms_used.extend(e.en for e in glossary.get_relevant_terms(all_target_text))

        for idx in to_translate_indices:
            block = target_blocks[idx]
            translated_protected = manual_translations.get(idx)
            if translated_protected is None:
                continue  # 未翻訳(nullのまま) -> 原文を残す

            _, mapping = protect_text(block.text, bold_tokens=block.bold_tokens)
            restored = restore_text(translated_protected, mapping)

            validation = validate_translation(
                original_text=block.text,
                translated_protected_text=translated_protected,
                restored_translated_text=restored,
                mapping_keys=list(mapping.keys()),
            )

            results[idx].flags = validation.flags
            if validation.safe_to_write:
                results[idx].translated_text = restored
                report.translated_blocks += 1
            else:
                report.failed_validation.append(
                    {
                        "page_index": block.page_index,
                        "classification": results[idx].classification,
                        "flags": validation.flags,
                        "original_text": block.text[:200],
                    }
                )
    else:
        # バッチ翻訳(通常のAPI翻訳エンジン経由)
        recent_tail_context: Optional[str] = None

        for chunk_indices in _chunked(to_translate_indices, batch_size):
            chunk_blocks = [target_blocks[i] for i in chunk_indices]
            protected_pairs = [protect_text(b.text, bold_tokens=b.bold_tokens) for b in chunk_blocks]
            protected_texts = [p[0] for p in protected_pairs]
            mappings = [p[1] for p in protected_pairs]

            combined_text = "\n".join(protected_texts)
            glossary_hints = glossary.get_relevant_terms(combined_text)
            report.glossary_terms_used.extend(e.en for e in glossary_hints)

            batch_context = context
            if recent_tail_context:
                batch_context = f"{context}\n\n{recent_tail_context}" if context else recent_tail_context

            translated_protected_list = translator.translate_batch(
                protected_texts, glossary_hints=glossary_hints, context=batch_context
            )

            for i, idx in enumerate(chunk_indices):
                mapping = mappings[i]
                translated_protected = translated_protected_list[i]
                restored = restore_text(translated_protected, mapping)

                validation = validate_translation(
                    original_text=chunk_blocks[i].text,
                    translated_protected_text=translated_protected,
                    restored_translated_text=restored,
                    mapping_keys=list(mapping.keys()),
                )

                results[idx].flags = validation.flags
                if validation.safe_to_write:
                    results[idx].translated_text = restored
                    report.translated_blocks += 1
                else:
                    report.failed_validation.append(
                        {
                            "page_index": chunk_blocks[i].page_index,
                            "classification": results[idx].classification,
                            "flags": validation.flags,
                            "original_text": chunk_blocks[i].text[:200],
                        }
                    )

            # 次のバッチへ、このバッチ最後のブロックの原文/訳文の末尾を文脈として引き継ぐ。
            # バッチの境界をまたいで文が続く場合(段組みの都合で分割された文など)に、
            # 言葉選び・語尾が食い違うのを防ぐため。
            last_idx = chunk_indices[-1]
            last_translated = results[last_idx].translated_text
            if last_translated:
                last_original = target_blocks[last_idx].text
                recent_tail_context = (
                    "直前のブロックの原文(末尾。文が続いている場合は自然に接続すること): "
                    f"…{last_original[-200:]}\n"
                    "直前のブロックの訳文(末尾。言葉選び・語尾をここに合わせて不自然な"
                    f"繰り返しを避けること): …{last_translated[-200:]}"
                )

    # 用語集の訳語が実際に一貫して使われているかを、全ブロックを横断してチェックする。
    # プロンプトで用語集を渡しているだけでは、LLMが本当にその訳語を使ったとは
    # 限らないため、事後の機械的な検証として行う。
    consistency_issues = check_glossary_consistency(results, glossary)
    for issue in consistency_issues:
        results[issue.block_index].flags.append(f"term_inconsistency:{issue.term_en}")
    report.glossary_inconsistencies = [issue.to_dict() for issue in consistency_issues]

    final_texts = [r.translated_text for r in results]
    write_status = write_translations(
        doc,
        target_blocks,
        final_texts,
        font_path=font_path,
        default_size=default_size,
        min_size=min_size,
        overflow_strategy=overflow_strategy,
    )
    for r, block, status in zip(results, target_blocks, write_status):
        r.written = status == "written"
        if status == "overflow":
            r.flags.append("layout_overflow")
            report.layout_overflow.append(
                {
                    "page_index": block.page_index,
                    "classification": r.classification,
                    "original_text": r.original_text[:200],
                }
            )

    doc.save(output_path)
    doc.close()

    report_path = str(Path(output_path).with_suffix("")) + ".report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    # 原文/訳文の対照表示HTML(自己完結、ブラウザで開くだけで確認できる)を
    # report.jsonと同様に毎回自動生成する。
    compare_html_path = str(Path(output_path).with_suffix("")) + ".compare.html"
    with open(compare_html_path, "w", encoding="utf-8") as f:
        f.write(build_comparison_html(results, input_path, output_path))
    report.compare_html_path = compare_html_path

    # ブロック単位の結果をJSONとして保存する。GUI(Flet等)がPDFやreport.jsonを
    # 再解析せずに、原文・訳文・フラグをそのまま読み込めるようにするため。
    blocks_json_path = str(Path(output_path).with_suffix("")) + ".blocks.json"
    with open(blocks_json_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "page_index": r.page_index,
                    "classification": r.classification,
                    "original_text": r.original_text,
                    "translated_text": r.translated_text,
                    "flags": r.flags,
                    "written": r.written,
                }
                for r in results
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )
    report.blocks_json_path = blocks_json_path

    if review_tsv_path:
        with open(review_tsv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["page", "classification", "original", "translated", "flags"])
            for r in results:
                writer.writerow(
                    [
                        r.page_index + 1,
                        r.classification,
                        r.original_text.replace("\n", " "),
                        (r.translated_text or "").replace("\n", " "),
                        ",".join(r.flags),
                    ]
                )

    return report
