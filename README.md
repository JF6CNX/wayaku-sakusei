# 論文和訳PDF書き込みツール

> **設計ドキュメント**: 化学系向けの詳細仕様は [SPEC.md](SPEC.md)、GUIアプリとしての設計は [APP_SPEC.md](APP_SPEC.md) を参照。
> 現状はCLIコア(SPEC.md M1〜M4)およびFlet製デスクトップGUI(ライブラリ画面+リーダー画面)を実装済み。DeepL/Googleの用語集連携・要約機能はまだ未実装。

英語(化学系)論文PDFを読み込み、本文テキストを検出して和訳に置き換えた新しいPDFを出力するプログラムです。
レイアウト(段組・図表位置)はできるだけ維持し、文章部分だけを日本語訳に置換します。
化学式・単位付き数値・NMR/MSデータなどはプレースホルダで保護し、翻訳エンジンに壊されないようにしてから復元します(詳細は [SPEC.md](SPEC.md) 4章)。

## 設計方針

1. **入力**: テキストが選択可能なデジタルPDF(スキャン画像PDFは非対応。OCR対応は将来拡張)
2. **抽出・分類**: `PyMuPDF (fitz)` でページごとにテキストブロックを取得し、本文/見出し/図表キャプション/数式/表データ/参考文献/ヘッダフッタ等に分類(SPEC.md 3章)。行末ハイフンで分断された単語(例: "organo-\nmetallic")も抽出時に結合する
3. **化学用語保護**: 化学式・単位付き数値・NMR/MSデータ行・略語をプレースホルダに変換してから翻訳エンジンに渡す(SPEC.md 4章)
4. **翻訳**: ブロック単位で翻訳エンジンに投げる。エンジンは差し替え可能(プラグイン方式)。用語集(分野別+ユーザー)をプロンプトに反映
5. **検証**: プレースホルダ欠落・数値欠落・空訳・長さ異常を自動チェックし、危険な訳文は書き込まず原文を残す(SPEC.md 7章)
6. **書き込み**: 元のテキスト領域を白塗りで消去(redaction)し、同じ矩形内に和訳を再流し込み
   - 日本語はデフォルトPDFフォントで表示できないため、日本語TTFフォント(Noto Sans JP等)を埋め込む
   - 訳文が長い場合はフォントサイズを縮小 → それでも収まらなければ矩形を下方向に拡張 → なお収まらなければ**原文を消さずに残す**(SPEC.md 8章)
7. **配布のしやすさ**: 翻訳エンジンのAPIキーは `.env` で管理。エンジンは起動時に `--engine` オプションか `config.yaml` で選択

## ディレクトリ構成

```
wayaku_sakusei/
├── README.md / SPEC.md / APP_SPEC.md
├── requirements.txt / .env.example / config.yaml
├── main.py                     # CLIエントリポイント(翻訳)
├── learn_glossary.py           # CLIエントリポイント(用語集への学習)
├── core/
│   ├── classify.py              # テキストブロック分類
│   ├── protect.py               # 化学表記の保護・復元
│   ├── glossary.py              # 用語集の読み込み・統合
│   ├── glossary_learning.py     # 翻訳済みデータから用語集TSVへの取り込み
│   ├── validate.py              # 翻訳後の自動検証
│   ├── pdf_io.py                 # PDF抽出・書き込み(fitz)
│   └── pipeline.py               # 上記を統合するオーケストレーション
├── translators/
│   ├── base.py                  # 翻訳エンジンの共通インターフェース
│   ├── claude_translator.py     # Anthropic Claude API実装(用語集・文脈対応)
│   ├── deepl_translator.py      # DeepL API実装
│   └── google_translator.py     # Google Cloud Translation API実装
├── glossaries/                   # 内蔵用語集(共通+分野別TSV)
├── tests/                        # pytest(APIキー不要で実行可能)
└── fonts/
    └── (NotoSansJP-Regular.ttf などをここに配置)
```

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env   # 使うエンジンのAPIキーを記入
```

日本語フォント(例: [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP))の
TTFファイルを `fonts/NotoSansJP-Regular.ttf` に配置してください
(`config.yaml` の `font.path` で参照先を変更できます)。

## 使い方

```bash
python main.py --input paper.pdf --output paper_ja.pdf --engine claude --field organic

# arXivやDOIを直接指定することもできる
python main.py --input 2301.12345 --engine claude
python main.py --input 10.1021/acs.jcim.5c02794 --engine claude   # オープンアクセスかつUNPAYWALL_EMAIL設定時のみ
```

- `--input`: PDFファイルパスの他、arXiv ID/URL、DOIも指定可能(下記「arXiv/DOIからの取得」参照)
- `--engine`: `claude` / `deepl` / `google` から選択(既定は config.yaml の設定)
- `--field`: 分野別用語集を追加読み込み(`organic` / `inorganic` / `analytical` / `physical` / `polymer` / `materials` / `general`)
- `--glossary`: 追加のユーザー用語集TSV(内蔵用語集より優先)
- `--pages`: 対象ページ範囲(例: `"1-5,8"`)。省略時は全ページ
- `--translate-refs`: 参考文献セクションも翻訳する(既定では除外)
- `--dry-run`: 翻訳・書き込みを行わず、抽出・分類結果だけ確認(APIキー不要)
- `--review-tsv`: 原文/訳文/検証フラグの対訳TSVを出力
- `--manual-file`: APIキーなしで翻訳する場合に使うJSONファイル(下記「APIキーなしで翻訳する」参照)

実行後、以下が自動生成されます。

- `<出力名>.report.json` — 翻訳ブロック数・スキップ内訳・検証失敗ブロック・レイアウトに収まらなかったブロック・**用語集の訳語が使われていない可能性がある箇所**・使用した用語集エントリ
- `<出力名>.compare.html` — **原文/訳文の対照表示**(ブラウザで開くだけで確認できる自己完結型HTML)。ブロックごとに原文と訳文を左右に並べ、「要注意のみ」(検証フラグ・用語不一致付き)・「未翻訳のみ」で絞り込み、キーワード検索、クリックでの強調表示ができる

## arXiv/DOIからの取得

[core/fetch.py](core/fetch.py)が`--input`の値を判定し、ローカルファイルが存在しなければ以下を試みます。

- **arXiv**(ID・URLどちらも可): 常に自動取得。arXivはプログラムからのアクセスを明示的に許可しているため
- **DOI**: [Unpaywall](https://unpaywall.org/)でオープンアクセスと確認できた場合のみ自動取得。`.env`に実在する連絡先メールアドレス(`UNPAYWALL_EMAIL`)の設定が必須で、未設定またはオープンアクセスでない場合は自動取得を行わず、手動でのダウンロードを促すエラーになる(ペイウォールの回避はしない)

取得したPDFは`input/`フォルダに保存される。

## 用語一貫性の事後検証

[core/consistency.py](core/consistency.py)が、翻訳完了後に全ブロックを横断してチェックする。用語集にある英語表現が原文に出現するのに、対応する日本語訳が訳文中に見つからない場合、そのブロックに`term_inconsistency:<用語>`フラグを付け、`report.json`の`glossary_inconsistencies`と対照表示HTMLの両方に記録する。プロンプトで用語集を渡すだけでは実際に使われた保証にならないため、事後の機械的な検証として行う。

## APIキーなしで翻訳する(手作業モード)

`--manual-file` にファイルパスを指定すると、翻訳エンジン(APIキー)を使わずに翻訳できます。

```bash
# 1回目: 翻訳待ちブロックをJSONにエクスポート(APIキー不要)
python main.py --input paper.pdf --output paper_ja.pdf --field organic --manual-file work.json

# work.json の各ブロックの translated_text を埋める
# (Claude Codeとの会話でそのまま翻訳してもらう、または手動で翻訳して埋める)

# 2回目: 埋めたファイルを使ってPDFに書き込む
python main.py --input paper.pdf --output paper_ja.pdf --field organic --manual-file work.json
```

`translated_text` を `null` のままにしたブロックは原文のまま残ります。
`⟦CHEM_nnn⟧` 形式のプレースホルダは化学式・数値等を保護しているため、削除・改変せずそのまま残す必要があります。

## 用語集への学習(翻訳済みデータからの取り込み)

`--manual-file` で作った(`translated_text` が埋まっている)JSONファイルから、
新出の専門用語を抽出して用語集TSVに追記できます。AIモデルの学習ではなく、
翻訳時に使う訳語辞書への追記です(次回以降 `--glossary` / `--field` で再利用可能)。

```bash
# 1回目: 候補抽出用ファイルを書き出す
python learn_glossary.py --source work.json --learn-file learn.json

# learn.json の各ペアを見て、専門用語だけを candidate_terms に追加する
# (Claude Codeとの会話でそのまま抽出してもらうこともできる)

# 2回目: 埋めたファイルを用語集TSVに取り込む
python learn_glossary.py --source work.json --learn-file learn.json --glossary-file glossaries/learned_terms.tsv
```

既存の用語と訳語が食い違う場合は上書きせず、`conflicts` として報告されます
(`glossary-file` を直接見て手動で解決してください)。

## GUIアプリ(Flet)

CLIと同じ `core/` パイプラインを使うデスクトップGUIです(翻訳ロジックの再実装はしていません)。

```bash
python -m gui.app
```

- **ライブラリ画面**: 「+ 新規翻訳」から入力PDF・翻訳エンジン・分野を選んでジョブを作成。過去のジョブが一覧表示され、
  用語集不一致や未翻訳ブロックがあれば「要確認 N件」バッジが付く。
- **リーダー画面**: ジョブを開くと「原文」「対訳」「和訳」タブで結果を確認できる。「和訳」「対訳」タブでは、
  未翻訳のまま残ったブロックに `(未翻訳)`、用語集の訳語が使われていない箇所に `用語一貫性の不一致` の
  インライン注記が段落中にそのまま表示される。
- 翻訳はバックグラウンドスレッドで実行されるため、実行中もライブラリ画面の操作は可能(ジョブは「実行中」表示)。
- ジョブ一覧は `app_data/jobs.json` に保存される(gitignore対象。マシンローカルの状態)。
- 各ジョブの結果PDFと同じ場所に生成される `<出力ファイル名>.blocks.json` を読み込んで表示しているため、
  CLIで直接実行した過去の翻訳結果もこのファイルさえあればGUIで開ける。

## テスト

```bash
pytest tests/
```

APIキーなしで実行できます(翻訳エンジンはテスト用スタブに差し替え)。
PDF書き込み系のテストは、実行環境に日本語フォント(Windowsの `msgothic.ttc` 等)が
見つからない場合は自動的にスキップされます。

## 既知の制限事項

- **太字・イタリック・上付き/下付き文字の書式が失われる**: 1ブロックにつき1つのフォント・スタイルで描画するため、"et al."のイタリックや引用番号の上付き表記、化合物番号の太字などは通常の文字として描画される(内容自体は保持される)。混在スタイルを再現するには、スパン単位で複数回描画するリッチテキスト対応の書き込みロジックが必要で、現状は未実装。
- **数式は検出して除外するが、完全ではない**: 数式は文字ごとに精密配置されているためPDF抽出時に細かい断片ブロックに分解されることが多く、「equation」分類として検出・除外している(SPEC.md 3章)。ただし、数式の直前にある短い導入句(例: "where t_r")など、判定が曖昧なブロックは翻訳対象に残ることがある。
- **横並びのUI要素(ACCESSバー等)は縦流しテキストとして扱われる**: 改行を自然な折り返しに変換することで多くの場合収まるようになったが、元のアイコン・区切り線などの視覚的な構造は再現されない。
- **図の中の文字は翻訳されない**: 図は画像として埋め込まれているため、テキストとして抽出できない(OCR対応は未実装)。図のキャプション自体は翻訳される。
- **罫線の無い表は、日本語訳が長くて元の矩形に収まらないと原文のまま残る**: 表データ(`table_data`分類)は改行を保ったまま描画するが、列そのものを再構成しているわけではないため、訳文が長い場合は安全側に倒して原文表示のままになることが多い。
- **段落の完全な再構成はしていない**: PDF抽出時の「行末ハイフン結合」は行うが、段組み・ページをまたいで分割された複数ブロックを1つの翻訳単位に統合してはいない。バッチ内・バッチ間の文脈引き継ぎで一貫性を補強しているのみ。
- **参考文献番号・図表番号の内部リンク保持は未検証**: 元PDFにクリック可能な内部リンク注釈があった場合、白塗り(redaction)で消える可能性が高い。

## 未実装・今後の課題

- [ ] スキャン画像PDF向けのOCR対応(数式・図中文字の認識含む。Nougat/pix2tex等の専用モデルは未使用)
- [ ] DeepL Glossary API / Google Cloud Translation Glossary 連携(現状プロンプト経由の用語集反映はClaudeエンジンのみ)
- [ ] 略語の「初出展開+以降は略語」制御(現状は略語を常に保護するのみ)
- [ ] セクション単位の部分翻訳(Methodsだけ翻訳する等。現状は`--pages`によるページ単位のみ)
- [ ] 翻訳APIのレート制限対応の詳細実装・中断再開キャッシュ(SPEC.md 9章)
- [ ] 論文要約機能(SPEC.md 10章)
- [ ] Markdown/Wordへのエクスポート(数式をLaTeXのまま保持)
- [ ] GUIのPyInstaller配布パッケージ化(現状は `python -m gui.app` での起動のみ)
- [ ] リッチテキスト(太字・イタリック・上付き文字)を保ったままの書き込み
- [ ] 横並びUI要素専用の描画ロジック(項目ごとに個別の矩形を持たせる)
