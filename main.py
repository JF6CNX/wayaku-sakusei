import argparse
from typing import List, Optional

import yaml
from dotenv import load_dotenv

from core.glossary import VALID_FIELDS, build_glossary
from core.pipeline import run_pipeline
from translators import get_translator


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_pages(spec: Optional[str]) -> Optional[List[int]]:
    """"1-5,8" のようなページ指定を [1,2,3,4,5,8] に変換する(1-indexed)。"""
    if not spec:
        return None
    pages: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start, end = int(start_str), int(end_str)
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    return pages


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="論文PDFを和訳して書き込むツール")
    parser.add_argument("--input", required=True, help="入力PDFパス")
    parser.add_argument("--output", help="出力PDFパス(省略時は <input>_ja.pdf)")
    parser.add_argument(
        "--engine",
        default=None,
        choices=["claude", "deepl", "google"],
        help="翻訳エンジン(省略時は config.yaml の設定)",
    )
    parser.add_argument(
        "--field",
        default="general",
        choices=sorted(VALID_FIELDS),
        help="分野別用語集を追加読み込みする分野",
    )
    parser.add_argument("--glossary", default=None, help="追加のユーザー用語集TSVファイル")
    parser.add_argument("--pages", default=None, help='対象ページ範囲(例: "1-5,8")。省略時は全ページ')
    parser.add_argument(
        "--translate-refs",
        action="store_true",
        help="参考文献セクションも翻訳する(既定では除外)",
    )
    parser.add_argument("--password", default=None, help="暗号化PDFのパスワード")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="翻訳・書き込みを行わず、抽出・分類結果だけを表示する",
    )
    parser.add_argument(
        "--review-tsv",
        default=None,
        help="原文/訳文/検証フラグの対訳TSVを出力するパス",
    )
    parser.add_argument(
        "--manual-file",
        default=None,
        help=(
            "APIキーなしで翻訳する場合に使うJSONファイルのパス。"
            "指定したファイルが無ければ翻訳待ちブロックをエクスポートして終了し、"
            "既にtranslated_textを埋めたファイルがあればそれを使ってPDFを書き込む。"
            "指定時は --engine は不要。"
        ),
    )
    return parser


def main():
    load_dotenv()
    config = load_config()

    parser = build_arg_parser()
    args = parser.parse_args()

    engine = args.engine or config.get("engine", "claude")
    output_path = args.output or args.input.rsplit(".pdf", 1)[0] + "_ja.pdf"
    pages = parse_pages(args.pages)

    glossary = build_glossary(field=args.field, user_glossary_path=args.glossary)

    # dry-runと--manual-fileはAPIキー(翻訳エンジン)を必要としない
    translator = None
    if not args.dry_run and not args.manual_file:
        translator = get_translator(
            engine,
            field=args.field,
            source_lang=config["translation"]["source_lang"],
            target_lang=config["translation"]["target_lang"],
        )

    report = run_pipeline(
        input_path=args.input,
        output_path=output_path,
        translator=translator,
        glossary=glossary,
        font_path=config["font"]["path"],
        default_size=config["font"]["default_size"],
        min_size=config["font"]["min_size"],
        batch_size=config["translation"]["batch_size"],
        overflow_strategy=config["layout"]["overflow_strategy"],
        translate_refs=args.translate_refs,
        pages=pages,
        dry_run=args.dry_run,
        review_tsv_path=args.review_tsv,
        password=args.password,
        manual_translation_path=args.manual_file,
    )

    if args.dry_run:
        print(f"抽出ブロック数: {report.total_blocks}")
        print(f"分類ごとの除外内訳: {report.skipped_by_classification}")
        return

    if report.manual_export_path:
        print(f"翻訳待ちブロックをエクスポートしました: {report.manual_export_path}")
        print("このファイルの各ブロックの translated_text を埋めてから、同じコマンドをもう一度実行してください。")
        return

    print(f"完了: {output_path}")
    print(f"翻訳ブロック数: {report.translated_blocks} / {report.total_blocks}")
    if report.failed_validation:
        print(f"検証失敗により原文のまま残したブロック: {len(report.failed_validation)}件")
    if report.layout_overflow:
        print(f"レイアウトに収まらず原文のまま残したブロック: {len(report.layout_overflow)}件")


if __name__ == "__main__":
    main()
