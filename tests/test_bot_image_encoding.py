from __future__ import annotations

import base64
import io

import pytest
from PIL import Image


def test_encode_image_for_vision_rejects_invalid_image_bytes():
    import bot

    with pytest.raises(ValueError, match="Invalid image"):
        bot._encode_image_for_vision(b"not an image")


def test_encode_image_for_vision_converts_to_bounded_jpeg():
    import bot

    src = Image.new("RGBA", (1400, 900), (255, 0, 0, 128))
    raw = io.BytesIO()
    src.save(raw, format="PNG")

    image_b64 = bot._encode_image_for_vision(raw.getvalue())
    encoded = base64.b64decode(image_b64)
    result = Image.open(io.BytesIO(encoded))

    assert result.format == "JPEG"
    assert result.mode == "RGB"
    assert max(result.size) <= 1024
