"""Executable NyayOne runtime-identity controls for NYAY-20."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.integrations.github import GitHubClient
from app.integrations import storage
from app.services.otp_sender import HttpOtpSender
from app.services.providers.payment_provider import (
    DETERMINISTIC_SIGNING_KEY as PAYMENT_SIGNING_KEY,
)
from app.services.providers.video_provider import (
    DETERMINISTIC_SIGNING_KEY as VIDEO_SIGNING_KEY,
)


def test_default_runtime_identity_is_nyayone_owned() -> None:
    configured = Settings(_env_file=None)
    assert configured.app_name == "NyayOne"
    assert configured.github_repository == "rajeevbarnwal/NyayOne"
    assert configured.github_repo_url == "https://github.com/rajeevbarnwal/NyayOne"
    assert configured.jira_project_key == "NYAY"
    assert configured.jira_board_id == 68
    assert configured.auth_session_cookie_name == "nyayone_session"


def test_generic_storage_defaults_do_not_share_the_legacy_namespace(
    monkeypatch,
    tmp_path,
) -> None:
    adapter = storage.FilesystemStorageAdapter(tmp_path)
    assert adapter.public_base_url == "http://localhost:1135"

    captured: list[str] = []

    def capture(root: str):
        captured.append(root)
        return object()

    monkeypatch.setattr(storage, "FilesystemStorageAdapter", capture)
    storage.get_storage_adapter()
    assert captured == ["/tmp/nyayone_storage"]


def test_github_client_uses_nyayone_metadata() -> None:
    client = GitHubClient(repository="rajeevbarnwal/NyayOne")
    assert client.repository_url == "https://api.github.com/repos/rajeevbarnwal/NyayOne"
    assert client._headers()["User-Agent"] == "NyayOne"


def test_http_otp_sender_uses_nyayone_message(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    HttpOtpSender("https://otp.example.test/send").send("+910000000000", "123456")
    assert captured["url"] == "https://otp.example.test/send"
    assert captured["json"] == {
        "to": "+910000000000",
        "message": "Your NyayOne verification code is 123456",
    }


def test_deterministic_provider_namespaces_are_nyayone_owned() -> None:
    assert PAYMENT_SIGNING_KEY == b"nyayone-deterministic-payment-test-key"
    assert VIDEO_SIGNING_KEY == b"nyayone-deterministic-video-test-key"
