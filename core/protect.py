"""化学表記の保護・復元(SPEC.md 4.1)。

翻訳エンジンに渡す前に、化学式・単位付き数値・NMR/MS/IRデータ行・略語などを
プレースホルダ(例: ⟦CHEM_001⟧)に置換して保護し、翻訳後に元の文字列へ復元する。
LLMによる数値の書き換えや化学式の破壊を防ぐのが目的。
"""

import re
from typing import Dict, List, Optional, Tuple

PLACEHOLDER_PATTERN = re.compile(r"⟦CHEM_(\d+)⟧")


def _placeholder(n: int) -> str:
    return f"⟦CHEM_{n:03d}⟧"


# --- 元素記号(大文字小文字を区別。誤検出を減らすため厳密な表記のみ許可) ---
_ELEMENTS = [
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu",
]
# 長い記号から順にマッチさせないと "Cl" が "C" と "l" に分解されてしまう
_ELEMENTS_SORTED = sorted(_ELEMENTS, key=len, reverse=True)
_ELEMENT_TOKEN = r"(?:" + "|".join(_ELEMENTS_SORTED) + r")\d*"

# 2トークン以上連続した場合のみ「化学式」とみなす(単独の元素記号は普通の単語と
# 区別がつかないため誤検出を避ける。例: "In this study" の "In" は保護しない)
_FORMULA_RE = re.compile(r"\b(?:" + _ELEMENT_TOKEN + r"){2,}\b")

_BRACKET_COMPLEX_RE = re.compile(r"\[[^\[\]\n]{1,60}\]\d*[+\-]{0,2}")

_INCHI_RE = re.compile(r"InChI=\S+")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_URL_RE = re.compile(r"https?://\S+")
_CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")

_DELTA_RE = re.compile(r"δ\s*[-+]?\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?")
_RF_RE = re.compile(r"\bR\s*f\s*=\s*[-+]?\d+(?:\.\d+)?")

_UNITS = [
    "kcal/mol", "kJ/mol", "mA/cm2", "mA/cm²", "cm-1", "cm⁻¹",
    "mmol", "μmol", "umol", "mol", "mM", "μg", "ug", "mg", "g",
    "mL", "μL", "uL", "L", "°C", "K", "ppm", "MHz", "GHz", "Hz",
    "nm", "Å", "mV", "eV", "rpm", "%", "h", "min", "s",
]
_UNITS_SORTED = sorted(_UNITS, key=len, reverse=True)
_UNIT_VALUE_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?\s*(?:"
    + "|".join(re.escape(u) for u in _UNITS_SORTED)
    + r")(?![A-Za-z0-9])"  # 末尾が"%"等の非単語文字でも \b が効くように否定先読みにする
)

_ABBREVIATIONS = [
    "GC-MS", "HRMS", "MALDI", "DMSO", "DFT", "HOMO", "LUMO",
    "TON", "TOF", "THF", "DMF", "DCM", "dba", "dppf", "NMR",
    "HPLC", "TLC", "ESI", "XRD", "EDX", "SEM", "TEM", "XPS",
    "TGA", "DSC", "GPC", "ATR", "IR", "UV",
]
_ABBREVIATION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\b"
)

# 太字トークンのうち「化合物番号らしい」ものだけを保護対象にする(例: 2a, 13, (3b))。
# タイトルや見出しが太字フォントで組まれている論文が多く、フィルタなしでは
# 見出し中の通常の単語まで保護してしまい翻訳できなくなるため。
_COMPOUND_LABEL_RE = re.compile(r"^\(?\d{1,3}[a-zA-Z]{0,2}\)?[,']{0,2}$")

_SPECTRAL_LINE_PATTERNS = [
    re.compile(r"^\s*\d*H\s+NMR"),
    re.compile(r"^\s*\d*C\{?1?H?\}?\s+NMR"),
    re.compile(r"^\s*NMR\s*\("),
    re.compile(r"^\s*HRMS"),
    re.compile(r"^\s*ESI-MS"),
    re.compile(r"^\s*MS\s*\(ESI"),
    re.compile(r"^\s*IR\s*\("),
    re.compile(r"^\s*Anal\.\s*Calcd"),
    re.compile(r"^\s*UV-vis"),
    re.compile(r"^\s*\[α\]"),
]

# 適用順序: より具体的・広範囲なパターンを先に適用する
_ORDERED_PATTERNS: List[re.Pattern] = [
    _INCHI_RE,
    _URL_RE,
    _DOI_RE,
    _CAS_RE,
    _BRACKET_COMPLEX_RE,
    _FORMULA_RE,
    _DELTA_RE,
    _RF_RE,
    _UNIT_VALUE_RE,
    _ABBREVIATION_RE,
]


class _Allocator:
    def __init__(self, start: int = 1):
        self._n = start
        self.mapping: Dict[str, str] = {}

    def add(self, original: str) -> str:
        ph = _placeholder(self._n)
        self.mapping[ph] = original
        self._n += 1
        return ph


def _is_spectral_line(line: str) -> bool:
    return any(p.search(line) for p in _SPECTRAL_LINE_PATTERNS)


def protect_text(
    text: str, bold_tokens: Optional[List[str]] = None
) -> Tuple[str, Dict[str, str]]:
    """text 中の化学表記をプレースホルダに置換する。

    Args:
        text: 保護対象のテキスト(改行はブロック内の行区切りを表す)
        bold_tokens: フォント情報から検出した太字トークン(化合物番号候補)。
            PDF書き込み側(pdf_io.py)がスパン情報を持っている場合に渡す。

    Returns:
        (protected_text, mapping): mapping は placeholder -> 元の文字列
    """
    allocator = _Allocator()

    # 1. 行単位でNMR/MS/IR等のスペクトルデータ行を丸ごと保護
    lines = text.split("\n")
    protected_lines = []
    for line in lines:
        if line.strip() and _is_spectral_line(line):
            protected_lines.append(allocator.add(line))
        else:
            protected_lines.append(line)
    working = "\n".join(protected_lines)

    # 2. 太字トークンのうち化合物番号らしいものだけを先に保護しておく
    if bold_tokens:
        label_tokens = [t for t in bold_tokens if t and _COMPOUND_LABEL_RE.match(t)]
        for token in sorted(set(label_tokens), key=len, reverse=True):
            working = working.replace(token, allocator.add(token))

    # 3. 残りのパターンを順に適用
    for pattern in _ORDERED_PATTERNS:

        def _sub(match: "re.Match") -> str:
            return allocator.add(match.group(0))

        working = pattern.sub(_sub, working)

    return working, allocator.mapping


# classify.py から化学式らしさの判定に再利用するための公開エイリアス
FORMULA_RE = _FORMULA_RE


def restore_text(text: str, mapping: Dict[str, str]) -> str:
    """protect_text で発行したプレースホルダを元の文字列に復元する。"""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def find_surviving_placeholders(text: str) -> List[str]:
    """text 中に残っているプレースホルダ(⟦CHEM_nnn⟧)を列挙する。"""
    return [f"⟦CHEM_{n}⟧" for n in PLACEHOLDER_PATTERN.findall(text)]
