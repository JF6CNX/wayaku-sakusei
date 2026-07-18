"""翻訳済みPDFのデータ(--manual-file で作ったJSON)を取り込み、新出の専門用語を
用語集TSVに追記するCLIツール。

AIモデルを学習させるのではなく、翻訳時に使う訳語辞書(用語集TSV)への追記である
点に注意(main.pyの --glossary で読み込めるファイルを更新する)。

使い方:
    # 1回目: 候補抽出用ファイルを書き出す
    python learn_glossary.py --source output/manual_p1-2.json --learn-file output/learn_candidates.json

    # このファイルの各ペアを見て candidate_terms を埋める(人手 or この会話でのClaude)

    # 2回目: 埋めたファイルを用語集TSVに取り込む
    python learn_glossary.py --source output/manual_p1-2.json --learn-file output/learn_candidates.json --glossary-file glossaries/learned_terms.tsv
"""

import argparse
from pathlib import Path

from core.glossary_learning import export_learning_candidates, import_learned_terms


def main():
    parser = argparse.ArgumentParser(
        description="翻訳済みJSONから専門用語を抽出し、用語集TSVに取り込む"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="翻訳済みJSON(main.py --manual-file で作った、translated_textが埋まっているファイル)",
    )
    parser.add_argument(
        "--learn-file",
        required=True,
        help="候補抽出用ファイルのパス。存在しなければエクスポートし、存在すれば取り込みを行う",
    )
    parser.add_argument(
        "--glossary-file",
        default="glossaries/learned_terms.tsv",
        help="追記先の用語集TSV(main.pyの --glossary でそのまま使える)",
    )
    args = parser.parse_args()

    learn_file = Path(args.learn_file)
    glossary_file = Path(args.glossary_file)

    if not learn_file.exists():
        count = export_learning_candidates(Path(args.source), learn_file)
        print(f"候補抽出用ファイルを書き出しました: {learn_file}({count}ペア)")
        print(
            "このファイルの各ペアを見て、専門用語だけを candidate_terms に "
            '{"en": "...", "ja": "...", "note": "..."} の形式で追加してから、'
            "同じコマンドをもう一度実行してください。"
        )
        return

    result = import_learned_terms(learn_file, glossary_file)
    print(f"用語集を更新しました: {glossary_file}")
    print(f"追加: {len(result.added)}件")
    if result.skipped_duplicates:
        print(f"既に同じ訳語で登録済み(スキップ): {len(result.skipped_duplicates)}件")
    if result.conflicts:
        print(f"訳語の食い違いにより取り込まなかった項目: {len(result.conflicts)}件")
        for c in result.conflicts:
            print(f"  - {c['en']}: 既存「{c['existing_ja']}」 vs 新規「{c['new_ja']}」")
        print("これらは手動で glossary-file を確認し、必要であれば直接編集してください。")


if __name__ == "__main__":
    main()
