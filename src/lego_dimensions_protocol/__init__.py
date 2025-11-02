"""High level interface for the LEGO Dimensions portal.

This package provides modern, typed utilities for interacting with the
LEGO Dimensions USB portal.  The :class:`~lego_dimensions_protocol.gateway.Gateway`
class is the main entry point and can be imported directly::

    from lego_dimensions_protocol import Gateway

The package exposes protocol level helpers that are designed to remain
stable and easy to integrate with contemporary Python software.
"""

from __future__ import annotations

from .characters import CharacterInfo, get_character, iter_characters
from .editor import TagEditor, TagWritePlan
from .gateway import Gateway, Pad, PortalNotFoundError, RGBColor
from .lstf import LSTFError, LSTFProgram, PadCommand, PadTrack, load_lstf
from .lstf_player import LSTFManager
from .morse import demo as morse_demo, send_character, send_text
from .rfid import TagEvent, TagEventType, TagTracker, TagTrackerError, watch_pads
from .rfid_demo import LightAction, run_rfid_demo
from .viewer import CharacterViewer
from .studio import TagStudio

__all__ = [
    "Gateway",
    "Pad",
    "PortalNotFoundError",
    "RGBColor",
    "TagEditor",
    "TagWritePlan",
    "CharacterInfo",
    "get_character",
    "iter_characters",
    "TagTracker",
    "TagTrackerError",
    "TagEvent",
    "TagEventType",
    "watch_pads",
    "LSTFError",
    "LSTFProgram",
    "PadCommand",
    "PadTrack",
    "load_lstf",
    "LSTFManager",
    "CharacterViewer",
    "LightAction",
    "TagStudio",
    "run_rfid_demo",
    "send_character",
    "send_text",
    "morse_demo",
]

__version__ = "0.1.0"
