from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
