from abc import ABC, abstractmethod
from typing import List, Optional

from core.glossary import GlossaryEntry


class BaseTranslator(ABC):
    """全ての翻訳エンジン実装が満たすインターフェース。

    新しいエンジンを追加する場合は、このクラスを継承して
    translate_batch を実装し、translators/__init__.py の ENGINES に登録する。
    """

    def __init__(self, source_lang: str = "en", target_lang: str = "ja", **kwargs):
        self.source_lang = source_lang
        self.target_lang = target_lang

    @abstractmethod
    def translate_batch(
        self,
        texts: List[str],
        glossary_hints: Optional[List[GlossaryEntry]] = None,
        context: Optional[str] = None,
    ) -> List[str]:
        """複数のテキストブロック(化学表記はプレースホルダ保護済み)をまとめて翻訳する。

        Args:
            texts: 翻訳対象テキスト(⟦CHEM_nnn⟧ プレースホルダを含みうる)
            glossary_hints: このバッチに関連する用語集エントリ(訳語を固定したい語のみ)
            context: 論文タイトル・要旨など、訳語の一貫性を保つための文脈情報

        入力と出力のリストは同じ順序・同じ長さでなければならない。
        (LLM系エンジンでブロック数がずれると、後段のPDF書き込みで
        訳文と矩形の対応が崩れるため、実装側で必ず件数を保証すること)

        プレースホルダ ⟦CHEM_nnn⟧ は改変・削除・翻訳せずそのまま出力に残すこと。
        """
        raise NotImplementedError

    def translate(self, text: str) -> str:
        return self.translate_batch([text])[0]
