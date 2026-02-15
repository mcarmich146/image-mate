# -*- coding: utf-8 -*-
"""QGIS plugin entrypoint for Image Mate."""


def classFactory(iface):
    from .plugin import ImageMatePlugin

    return ImageMatePlugin(iface)
