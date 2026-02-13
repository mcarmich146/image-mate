from __future__ import annotations

import unittest

from PIL import Image, ImageChops, ImageDraw

from backend.app import services


class Mp4GeolocationTests(unittest.TestCase):
    def test_extract_tile_quad_lonlat_polygon(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [-122.0, 37.0],
                [-121.0, 37.0],
                [-121.0, 38.0],
                [-122.0, 38.0],
                [-122.0, 37.0],
            ]],
        }
        quad = services._extract_tile_quad_lonlat(geom)
        self.assertIsNotNone(quad)
        self.assertEqual(len(quad), 4)

    def test_extract_tile_quad_lonlat_densified_ring(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [-122.0, 37.0],
                [-121.5, 37.0],
                [-121.0, 37.0],
                [-121.0, 37.5],
                [-121.0, 38.0],
                [-121.5, 38.0],
                [-122.0, 38.0],
                [-122.0, 37.5],
                [-122.0, 37.0],
            ]],
        }
        quad = services._extract_tile_quad_lonlat(geom)
        self.assertIsNotNone(quad)
        self.assertEqual(len(quad), 4)

    def test_ordered_tile_quad_canvas_points(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [-122.0, 37.0],
                [-121.0, 37.1],
                [-121.1, 38.1],
                [-122.1, 38.0],
                [-122.0, 37.0],
            ]],
        }
        quad = services._ordered_tile_quad_canvas_points(
            geometry=geom,
            viewport_bounds=(-123.0, 36.0, -120.0, 39.0),
            canvas_size=(1200, 800),
        )
        self.assertIsNotNone(quad)
        self.assertEqual(len(quad), 4)
        # TL then TR then BR then BL ordering in y-down canvas space.
        top_mid_y = (quad[0][1] + quad[1][1]) * 0.5
        bottom_mid_y = (quad[2][1] + quad[3][1]) * 0.5
        left_mid_x = (quad[0][0] + quad[3][0]) * 0.5
        right_mid_x = (quad[1][0] + quad[2][0]) * 0.5
        self.assertLess(top_mid_y, bottom_mid_y)
        self.assertLess(left_mid_x, right_mid_x)

    def test_solve_perspective_coeffs_identity(self):
        dst = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
        src = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
        coeffs = services._solve_perspective_coeffs(dst, src)
        self.assertIsNotNone(coeffs)

        def project(x: float, y: float):
            a, b, c, d, e, f, g, h = coeffs
            den = (g * x) + (h * y) + 1.0
            return ((a * x + b * y + c) / den, (d * x + e * y + f) / den)

        for x, y in dst:
            px, py = project(x, y)
            self.assertAlmostEqual(px, x, places=6)
            self.assertAlmostEqual(py, y, places=6)

    def test_datetime_label_draws_on_small_and_large_frames(self):
        small_before = Image.new("RGB", (320, 240), (0, 0, 0))
        small_after = small_before.copy()
        services._draw_datetime_label(small_after, "2026-02-13T12:34:56Z")
        self.assertIsNotNone(ImageChops.difference(small_before, small_after).getbbox())

        large_before = Image.new("RGB", (4096, 2160), (0, 0, 0))
        large_after = large_before.copy()
        services._draw_datetime_label(large_after, "2026-02-13T12:34:56Z")
        self.assertIsNotNone(ImageChops.difference(large_before, large_after).getbbox())

    def test_fit_label_font_increases_for_larger_canvas(self):
        text = "2026-02-13T12:34:56Z"
        small_canvas = Image.new("RGB", (320, 240), (0, 0, 0))
        large_canvas = Image.new("RGB", (4096, 2160), (0, 0, 0))
        small_draw = ImageDraw.Draw(small_canvas)
        large_draw = ImageDraw.Draw(large_canvas)
        _, small_size = services._fit_label_font(
            small_draw,
            text,
            small_canvas.size,
            target_width_ratio=0.5,
            max_height_ratio=0.14,
        )
        _, large_size = services._fit_label_font(
            large_draw,
            text,
            large_canvas.size,
            target_width_ratio=0.5,
            max_height_ratio=0.14,
        )
        self.assertGreaterEqual(large_size, small_size)


if __name__ == "__main__":
    unittest.main()
