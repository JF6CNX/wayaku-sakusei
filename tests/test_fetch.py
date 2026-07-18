import json
from unittest.mock import MagicMock, patch

import pytest

from core.fetch import (
    fetch_pdf,
    is_arxiv_reference,
    is_doi_reference,
    resolve_and_fetch,
    resolve_arxiv_pdf_url,
    resolve_doi_pdf_url,
)


def test_is_arxiv_reference_detects_bare_id_and_urls():
    assert is_arxiv_reference("2301.12345")
    assert is_arxiv_reference("2301.12345v2")
    assert is_arxiv_reference("https://arxiv.org/abs/2301.12345")
    assert is_arxiv_reference("https://arxiv.org/pdf/2301.12345.pdf")
    assert not is_arxiv_reference("10.1021/acs.jcim.5c02794")
    assert not is_arxiv_reference("paper.pdf")


def test_is_doi_reference_detects_bare_doi_and_urls():
    assert is_doi_reference("10.1021/acs.jcim.5c02794")
    assert is_doi_reference("https://doi.org/10.1021/acs.jcim.5c02794")
    assert is_doi_reference("doi.org/10.1021/acs.jcim.5c02794")
    assert not is_doi_reference("2301.12345")
    assert not is_doi_reference("paper.pdf")


def test_resolve_arxiv_pdf_url_from_bare_id():
    assert resolve_arxiv_pdf_url("2301.12345") == "https://arxiv.org/pdf/2301.12345.pdf"


def test_resolve_arxiv_pdf_url_from_abs_url():
    url = resolve_arxiv_pdf_url("https://arxiv.org/abs/2301.12345v2")
    assert url == "https://arxiv.org/pdf/2301.12345.pdf"


def test_resolve_arxiv_pdf_url_raises_on_no_match():
    with pytest.raises(ValueError):
        resolve_arxiv_pdf_url("not an arxiv reference at all")


def test_resolve_doi_pdf_url_returns_none_without_email(monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    assert resolve_doi_pdf_url("10.1021/acs.jcim.5c02794") is None


def test_resolve_doi_pdf_url_calls_unpaywall_when_email_given():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps(
        {"best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"}}
    ).encode("utf-8")
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda self, *a: None

    with patch("core.fetch.urllib.request.urlopen", return_value=fake_response) as mock_urlopen:
        url = resolve_doi_pdf_url("10.1021/acs.jcim.5c02794", email="test@example.com")

    assert url == "https://example.org/paper.pdf"
    mock_urlopen.assert_called_once()
    called_request = mock_urlopen.call_args[0][0]
    assert "test@example.com" in called_request.full_url


def test_resolve_doi_pdf_url_returns_none_when_not_open_access():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"best_oa_location": None}).encode("utf-8")
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda self, *a: None

    with patch("core.fetch.urllib.request.urlopen", return_value=fake_response):
        url = resolve_doi_pdf_url("10.1021/some-paywalled-doi", email="test@example.com")

    assert url is None


def test_fetch_pdf_writes_downloaded_bytes(tmp_path):
    fake_response = MagicMock()
    fake_response.read.return_value = b"%PDF-1.4 fake content"
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda self, *a: None

    dest = tmp_path / "downloaded.pdf"
    with patch("core.fetch.urllib.request.urlopen", return_value=fake_response):
        fetch_pdf("https://example.org/paper.pdf", dest)

    assert dest.exists()
    assert dest.read_bytes() == b"%PDF-1.4 fake content"


def test_resolve_and_fetch_arxiv(tmp_path):
    fake_response = MagicMock()
    fake_response.read.return_value = b"%PDF-1.4 fake arxiv content"
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda self, *a: None

    with patch("core.fetch.urllib.request.urlopen", return_value=fake_response):
        dest = resolve_and_fetch("2301.12345", tmp_path)

    assert dest.exists()
    assert dest.name == "arxiv-2301.12345.pdf"


def test_resolve_and_fetch_doi_raises_when_not_open_access(tmp_path, monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    with pytest.raises(ValueError, match="オープンアクセスPDFが見つかりませんでした"):
        resolve_and_fetch("10.1021/acs.jcim.5c02794", tmp_path)


def test_resolve_and_fetch_unrecognized_reference_raises(tmp_path):
    with pytest.raises(ValueError, match="判定できませんでした"):
        resolve_and_fetch("just some random text", tmp_path)
