from pathlib import Path

import pytest

# 開発機(Windows)に入っている日本語フォントをテスト用に借用する。
# 本番配布物には含めない(README/fonts/README.md 参照)。
_CANDIDATE_FONTS = [
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothR.ttc",
]


@pytest.fixture(scope="session")
def japanese_font_path():
    for candidate in _CANDIDATE_FONTS:
        if Path(candidate).exists():
            return candidate
    pytest.skip("テスト環境に日本語フォントが見つからないため、このテストをスキップします")
