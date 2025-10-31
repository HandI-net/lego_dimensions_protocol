"""High level interface for the LEGO Dimensions portal.

This package provides modern, typed utilities for interacting with the
LEGO Dimensions USB portal.  The :class:`~lego_dimensions_protocol.gateway.Gateway`
class is the main entry point and can be imported directly::

    from lego_dimensions_protocol import Gateway

The package exposes protocol level helpers that are designed to remain
stable and easy to integrate with contemporary Python software.
"""

from __future__ import annotations

from .gateway import Gateway, Pad, PortalNotFoundError, RGBColor

__all__ = ["Gateway", "Pad", "PortalNotFoundError", "RGBColor"]

__version__ = "0.1.0"
