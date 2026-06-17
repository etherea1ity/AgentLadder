from __future__ import annotations

import json
import urllib.request

from klara.infra.config.images import ImageModel, ImageProviderConfig
from klara.services.images.qwen import generate_qwen_image


def test_generate_qwen_image_posts_downloads_and_returns_local_asset(monkeypatch) -> None:
    """Qwen image service should persist short-lived provider URLs locally."""

    calls: list[urllib.request.Request | str] = []

    class FakeResponse:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return self.body

    def fake_urlopen(request_or_url, timeout: int) -> FakeResponse:
        calls.append(request_or_url)
        if isinstance(request_or_url, urllib.request.Request):
            payload = json.loads(request_or_url.data.decode("utf-8"))  # type: ignore[union-attr]
            assert payload["model"] == "qwen-image-2.0-pro"
            assert payload["parameters"]["size"] == "1024*1024"
            body = {
                "request_id": "req-1",
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"image": "https://provider.example/generated.png"}
                                ]
                            }
                        }
                    ]
                },
                "usage": {"width": 1024, "height": 1024},
            }
            return FakeResponse(json.dumps(body).encode("utf-8"))
        return FakeResponse(b"png-bytes")

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        "klara.services.images.qwen.save_image_bytes",
        lambda content, extension: ("data/assets/images/test.png", "/api/assets/local?path=data/assets/images/test.png"),
    )

    images = generate_qwen_image(
        provider=ImageProviderConfig(
            api="dashscope-multimodal-generation",
            endpoint="https://dashscope.example/generation",
            api_key_env="DASHSCOPE_API_KEY",
        ),
        model=ImageModel(id="qwen-image-2.0-pro", default_size="1024*1024"),
        prompt="draw Klara",
    )

    assert len(calls) == 2
    assert images[0].public_url == "/api/assets/local?path=data/assets/images/test.png"
    assert images[0].source_url == "https://provider.example/generated.png"
    assert images[0].width == 1024
    assert images[0].request_id == "req-1"

