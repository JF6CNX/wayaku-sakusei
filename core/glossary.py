"""用語集の読み込み・統合(SPEC.md 4.2, 4.3)。

内蔵の core_chemistry.tsv(常に読み込み)+ 分野別TSV(--field)+
ユーザー用語集(--glossary)を、この優先順位(ユーザー > 分野 > 共通)で統合する。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

GLOSSARY_DIR = Path(__file__).resolve().parent.parent / "glossaries"

CORE_GLOSSARY_NAME = "core_chemistry.tsv"

VALID_FIELDS = {
    "organic",
    "inorganic",
    "analytical",
    "physical",
    "polymer",
    "materials",
    "computational",
    "general",
}


@dataclass(frozen=True)
class GlossaryEntry:
    en: str
    ja: str
    note: str = ""


def load_tsv(path: Path) -> List[GlossaryEntry]:
    """TSVファイル(英語⇥日本語訳⇥備考(任意))を読み込む。

    先頭行がヘッダ("en"始まり)ならスキップする。空行・#始まりはコメントとして無視。
    """
    entries: List[GlossaryEntry] = []
    if not path.exists():
        raise FileNotFoundError(f"用語集ファイルが見つかりません: {path}")

    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip() or line.strip().startswith("#"):
                continue
            cols = line.split("\t")
            if line_no == 1 and cols[0].strip().lower() == "en":
                continue  # ヘッダ行
            if len(cols) < 2:
                continue
            en = cols[0].strip()
            ja = cols[1].strip()
            note = cols[2].strip() if len(cols) >= 3 else ""
            if en and ja:
                entries.append(GlossaryEntry(en=en, ja=ja, note=note))
    return entries


class Glossary:
    """統合済みの用語集。英語の長い語句から優先してマッチさせる。"""

    def __init__(self, entries: Optional[Iterable[GlossaryEntry]] = None):
        # キーは英語の小文字化(大文字小文字を無視した最長一致のため)
        self._by_key: Dict[str, GlossaryEntry] = {}
        if entries:
            for e in entries:
                self._by_key[e.en.lower()] = e

    def add(self, entry: GlossaryEntry) -> None:
        """既存エントリを上書きして追加する(後から追加した方が優先)。"""
        self._by_key[entry.en.lower()] = entry

    def merge(self, other: "Glossary") -> None:
        """other の内容をこの用語集に統合する(other の方が優先)。"""
        for entry in other.entries():
            self.add(entry)

    def entries(self) -> List[GlossaryEntry]:
        return list(self._by_key.values())

    def lookup(self, en: str) -> Optional[GlossaryEntry]:
        return self._by_key.get(en.lower())

    def get_relevant_terms(self, text: str) -> List[GlossaryEntry]:
        """text 中に出現する用語だけを抽出する(プロンプトを短く保つため)。

        長い語句から順にマッチさせ、大文字小文字は無視する。
        同じ位置に複数の語句がマッチしても、最初に見つかった(=最長の)ものを優先する。
        """
        text_lower = text.lower()
        matched: List[GlossaryEntry] = []
        # 長い英語表現から順に判定することで、部分文字列の重複マッチを避ける
        for entry in sorted(self._by_key.values(), key=lambda e: len(e.en), reverse=True):
            if entry.en.lower() in text_lower:
                matched.append(entry)
        return matched

    def __len__(self) -> int:
        return len(self._by_key)


def build_glossary(field: Optional[str] = None, user_glossary_path: Optional[str] = None) -> Glossary:
    """core → field → user の順に読み込んで統合する(後勝ち=ユーザーが最優先)。"""
    glossary = Glossary(load_tsv(GLOSSARY_DIR / CORE_GLOSSARY_NAME))

    if field and field != "general":
        if field not in VALID_FIELDS:
            raise ValueError(f"未対応の分野です: {field} (対応: {sorted(VALID_FIELDS)})")
        field_path = GLOSSARY_DIR / f"{field}.tsv"
        if field_path.exists():
            glossary.merge(Glossary(load_tsv(field_path)))

    if user_glossary_path:
        glossary.merge(Glossary(load_tsv(Path(user_glossary_path))))

    return glossary
