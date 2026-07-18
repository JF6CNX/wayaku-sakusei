"""原文/訳文の対照表示HTMLを生成する(SPEC.md UXの「対照表示」に相当)。

外部依存の無い自己完結型の静的HTMLファイルを1つ生成する。ブラウザで開くだけで、
ブロック単位に原文と訳文を並べて確認できる。行をクリックすると強調表示され、
フラグの付いたブロック(検証失敗・レイアウト超過等)や未翻訳ブロックだけを
絞り込むフィルタも備える。
"""

import html as html_module
from typing import List, Optional, Protocol


class ComparisonRow(Protocol):
    page_index: int
    classification: str
    original_text: str
    translated_text: Optional[str]
    flags: List[str]


def _escape(text: str) -> str:
    return html_module.escape(text).replace("\n", "<br>")


def _row_html(index: int, row: "ComparisonRow") -> str:
    is_untranslated = row.translated_text is None
    is_flagged = bool(row.flags)
    status = "untranslated" if is_untranslated else ("flagged" if is_flagged else "ok")

    flag_badges = "".join(f'<span class="badge">{_escape(f)}</span>' for f in row.flags)
    translated_html = (
        _escape(row.translated_text)
        if row.translated_text
        else '<span class="placeholder">(未翻訳・原文のまま)</span>'
    )

    return f"""
    <div class="row {status}" data-idx="{index}" data-status="{status}">
      <div class="meta">p.{row.page_index + 1} · {_escape(row.classification)}{flag_badges}</div>
      <div class="pair">
        <div class="cell original">{_escape(row.original_text)}</div>
        <div class="cell translated">{translated_html}</div>
      </div>
    </div>"""


_PAGE_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --border: #e5e7eb;
    --row-hover: #f3f4f6; --row-focus: #eef2ff; --focus-border: #6366f1;
    --flag-bg: #fef3c7; --flag-fg: #92400e;
    --untranslated-bg: #f9fafb;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16181d; --fg: #e5e7eb; --muted: #9ca3af; --border: #2d3138;
      --row-hover: #1f232b; --row-focus: #232a3d; --focus-border: #818cf8;
      --flag-bg: #451a03; --flag-fg: #fcd34d;
      --untranslated-bg: #1b1e24;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Yu Gothic", sans-serif;
    font-size: 14px; line-height: 1.6;
  }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); margin: 0 0 16px; font-size: 13px; }}
  .toolbar {{
    position: sticky; top: 0; background: var(--bg); padding: 8px 0 12px;
    display: flex; gap: 8px; align-items: center; border-bottom: 1px solid var(--border);
    margin-bottom: 12px; z-index: 10; flex-wrap: wrap;
  }}
  .toolbar button {{
    border: 1px solid var(--border); background: var(--bg); color: var(--fg);
    border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 13px;
  }}
  .toolbar button.active {{ background: var(--focus-border); color: white; border-color: var(--focus-border); }}
  .toolbar input {{
    flex: 1; min-width: 160px; padding: 6px 10px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--bg); color: var(--fg); font-size: 13px;
  }}
  .count {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
  .row {{
    border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px;
    cursor: pointer; overflow: hidden;
  }}
  .row:hover {{ background: var(--row-hover); }}
  .row.focused {{ background: var(--row-focus); border-color: var(--focus-border); }}
  .row.untranslated {{ background: var(--untranslated-bg); }}
  .meta {{
    font-size: 11px; color: var(--muted); padding: 6px 12px 0;
    display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  }}
  .badge {{
    background: var(--flag-bg); color: var(--flag-fg); border-radius: 4px;
    padding: 1px 6px; font-size: 10px;
  }}
  .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
  .cell {{ padding: 8px 12px 10px; overflow-wrap: break-word; }}
  .cell.original {{ border-right: 1px solid var(--border); }}
  .placeholder {{ color: var(--muted); font-style: italic; }}
  @media (max-width: 700px) {{
    .pair {{ grid-template-columns: 1fr; }}
    .cell.original {{ border-right: none; border-bottom: 1px solid var(--border); }}
  }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="subtitle">{subtitle}</p>
<div class="toolbar">
  <button data-filter="all" class="active">すべて</button>
  <button data-filter="flagged">要注意のみ</button>
  <button data-filter="untranslated">未翻訳のみ</button>
  <input type="text" id="search" placeholder="原文・訳文を検索...">
  <span class="count" id="count"></span>
</div>
<div id="rows">{rows}</div>
<script>
  const rows = Array.from(document.querySelectorAll('.row'));
  const buttons = Array.from(document.querySelectorAll('.toolbar button'));
  const search = document.getElementById('search');
  const countEl = document.getElementById('count');
  let currentFilter = 'all';

  function applyFilters() {{
    const q = search.value.trim().toLowerCase();
    let visible = 0;
    for (const row of rows) {{
      const status = row.dataset.status;
      const matchesFilter = currentFilter === 'all' || status === currentFilter;
      const matchesSearch = !q || row.textContent.toLowerCase().includes(q);
      const show = matchesFilter && matchesSearch;
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    }}
    countEl.textContent = visible + ' / ' + rows.length + ' 件';
  }}

  buttons.forEach(btn => btn.addEventListener('click', () => {{
    buttons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    applyFilters();
  }}));
  search.addEventListener('input', applyFilters);

  rows.forEach(row => row.addEventListener('click', () => {{
    const wasFocused = row.classList.contains('focused');
    rows.forEach(r => r.classList.remove('focused'));
    if (!wasFocused) row.classList.add('focused');
  }}));

  applyFilters();
</script>
</body>
</html>
"""


def build_comparison_html(results: List["ComparisonRow"], input_path: str, output_path: str) -> str:
    """原文/訳文の対照表示HTML(自己完結・単一ファイル)を組み立てて返す。"""
    total = len(results)
    translated = sum(1 for r in results if r.translated_text is not None)
    flagged = sum(1 for r in results if r.flags)

    rows_html = "\n".join(_row_html(i, r) for i, r in enumerate(results))
    subtitle = (
        f"{_escape(input_path)} → {_escape(output_path)} / "
        f"全{total}ブロック中{translated}件を翻訳(要注意フラグ: {flagged}件)"
    )

    return _PAGE_TEMPLATE.format(
        title="原文/訳文 対照表示",
        subtitle=subtitle,
        rows=rows_html,
    )
