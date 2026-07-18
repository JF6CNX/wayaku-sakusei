"""arXiv ID/URL または DOI を指定して、論文PDFを直接取得する。

- arXiv: arXivは投稿論文へのプログラムからのアクセスを明示的に許可しており、
  PDFのURLパターンも公開されている(https://arxiv.org/pdf/<id>.pdf)ため、
  常に安全に直接取得できる。
- DOI: DOI自体はPDFへのリンクではなく出版社のページへのリダイレクトである
  ことが多く、購読契約が無いと本文を取得できない場合が大半である。ここでは
  Unpaywall(オープンアクセス論文の所在を教えてくれる無料API)を使い、
  確実にオープンアクセスと判定された場合のみPDFへの直リンクを返す。
  Unpaywallの利用規約上、連絡先メールアドレスの送信が必須なため、
  環境変数 UNPAYWALL_EMAIL が設定されていない場合は問い合わせ自体を行わない
  (勝手にダミーのメールアドレスを送信することはしない)。
  ペイウォールの回避は行わない。
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

_USER_AGENT = "wayaku-sakusei-paper-translator/1.0 (https://github.com/JF6CNX/wayaku-sakusei)"


def is_arxiv_reference(s: str) -> bool:
    s = s.strip()
    return "arxiv.org" in s.lower() or bool(_ARXIV_ID_RE.fullmatch(s))


def is_doi_reference(s: str) -> bool:
    s = s.strip()
    if s.lower().startswith(("https://doi.org/", "http://doi.org/", "doi.org/")):
        return True
    return bool(_DOI_RE.match(s))


def resolve_arxiv_pdf_url(s: str) -> str:
    """arXivのID・URLからPDFの直リンクを組み立てる。"""
    match = _ARXIV_ID_RE.search(s.strip())
    if not match:
        raise ValueError(f"arXiv IDが見つかりません: {s}")
    arxiv_id = match.group(1)
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def _normalize_doi(doi: str) -> str:
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if doi.lower().startswith(prefix):
            return doi[len(prefix):]
    return doi


def resolve_doi_pdf_url(doi: str, email: Optional[str] = None) -> Optional[str]:
    """Unpaywallでオープンアクセスの所在を確認し、PDF直リンクを返す。

    見つからない場合(オープンアクセスでない、あるいはUNPAYWALL_EMAILが
    設定されていない)はNoneを返す。ペイウォールを回避する目的では使わない。
    """
    email = email or os.environ.get("UNPAYWALL_EMAIL")
    if not email:
        return None

    doi = _normalize_doi(doi)
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None

    best_location = data.get("best_oa_location") or {}
    return best_location.get("url_for_pdf") or best_location.get("url")


def fetch_pdf(url: str, dest_path: Path) -> None:
    """指定したURLからPDFをダウンロードし、dest_pathに保存する。"""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)


def resolve_and_fetch(reference: str, dest_dir: Path, email: Optional[str] = None) -> Path:
    """arXiv参照またはDOIからPDFを取得し、保存先パスを返す。

    自動取得できない場合(DOIでオープンアクセスが確認できない等)は
    ValueErrorを送出し、手動でのダウンロードを促す。
    """
    reference = reference.strip()

    if is_arxiv_reference(reference):
        pdf_url = resolve_arxiv_pdf_url(reference)
        match = _ARXIV_ID_RE.search(reference)
        filename = f"arxiv-{match.group(1)}.pdf"
        dest_path = dest_dir / filename
        fetch_pdf(pdf_url, dest_path)
        return dest_path

    if is_doi_reference(reference):
        pdf_url = resolve_doi_pdf_url(reference, email=email)
        if not pdf_url:
            raise ValueError(
                f"DOI '{reference}' のオープンアクセスPDFが見つかりませんでした"
                "(購読契約が必要な可能性があります、またはUNPAYWALL_EMAILが未設定です)。"
                "手動でPDFをダウンロードし、--input にファイルパスを指定してください。"
            )
        safe_name = _normalize_doi(reference).replace("/", "_")
        dest_path = dest_dir / f"doi-{safe_name}.pdf"
        fetch_pdf(pdf_url, dest_path)
        return dest_path

    raise ValueError(f"arXiv参照ともDOIとも判定できませんでした: {reference}")
