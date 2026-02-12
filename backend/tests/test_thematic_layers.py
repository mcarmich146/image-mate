from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException

from backend.app import main


class ThematicLayerRenderTests(unittest.TestCase):
    def test_compose_rgb_from_luma_maps_channels_correctly(self):
        r = Image.new("L", (1, 1), color=200)
        g = Image.new("L", (1, 1), color=100)
        b = Image.new("L", (1, 1), color=50)
        rgba = main._compose_rgb_from_luma(r, g, b)
        px = rgba.getpixel((0, 0))
        self.assertEqual(px, (200, 100, 50, 255))

    def test_render_thematic_tile_natural_and_false_are_not_black(self):
        class _Resp:
            def __init__(self, content: bytes):
                self.status_code = 200
                self.content = content
                self.text = ""

        def _png_luma(base: int) -> bytes:
            img = Image.new("L", (4, 4))
            img.putdata([base + i for i in range(16)])
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        natural_bands = {
            1: _png_luma(9),
            2: _png_luma(12),
            3: _png_luma(16),
        }
        false_bands = {
            2: _png_luma(8),
            3: _png_luma(11),
            4: _png_luma(15),
        }

        def fake_upstream(**kwargs):
            bidx = kwargs.get("bidx") or []
            band = int(bidx[0]) if bidx else 1
            if band in natural_bands:
                return _Resp(natural_bands[band]), "oauth_client_credentials"
            return _Resp(false_bands.get(band, _png_luma(0))), "oauth_client_credentials"

        with patch.object(main, "_cog_upstream_request", side_effect=fake_upstream):
            natural_bytes, _ = main._render_thematic_tile(
                z=10,
                x=20,
                y=30,
                source_url="s3://example/natural.tif",
                cloud_mask_url=None,
                contract_id=None,
                scale=1,
                buffer=0,
                tile_matrix_set_id="WebMercatorQuad",
                render_layer="natural",
            )
            false_bytes, _ = main._render_thematic_tile(
                z=10,
                x=20,
                y=30,
                source_url="s3://example/analytic.tif",
                cloud_mask_url=None,
                contract_id=None,
                scale=1,
                buffer=0,
                tile_matrix_set_id="WebMercatorQuad",
                render_layer="false_color",
            )

        natural = Image.open(BytesIO(natural_bytes)).convert("RGB")
        false_color = Image.open(BytesIO(false_bytes)).convert("RGB")
        n_extrema = natural.getextrema()
        f_extrema = false_color.getextrema()
        self.assertGreater(sum(ch[1] for ch in n_extrema), 0)
        self.assertGreater(sum(ch[1] for ch in f_extrema), 0)

    def test_false_color_falls_back_to_natural_when_band4_unavailable(self):
        class _Resp:
            def __init__(self, content: bytes):
                self.status_code = 200
                self.content = content
                self.text = ""

        def _png_rgb(r: int, g: int, b: int) -> bytes:
            img = Image.new("RGB", (2, 2), color=(r, g, b))
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        def fake_upstream(**kwargs):
            bidx = kwargs.get("bidx") or []
            if bidx == [4]:
                raise HTTPException(status_code=400, detail="band 4 unavailable")
            if bidx == [1, 2, 3]:
                return _Resp(_png_rgb(32, 64, 96)), "oauth_client_credentials"
            if bidx == [3] or bidx == [2]:
                return _Resp(_png_rgb(10, 10, 10)), "oauth_client_credentials"
            return _Resp(_png_rgb(0, 0, 0)), "oauth_client_credentials"

        with patch.object(main, "_cog_upstream_request", side_effect=fake_upstream):
            false_bytes, _ = main._render_thematic_tile(
                z=10,
                x=20,
                y=30,
                source_url="s3://example/visual.tif",
                cloud_mask_url=None,
                contract_id=None,
                scale=1,
                buffer=0,
                tile_matrix_set_id="WebMercatorQuad",
                render_layer="false_color",
            )

        rgb = Image.open(BytesIO(false_bytes)).convert("RGB")
        px = rgb.getpixel((0, 0))
        self.assertEqual(px, (32, 64, 96))


if __name__ == "__main__":
    unittest.main()
