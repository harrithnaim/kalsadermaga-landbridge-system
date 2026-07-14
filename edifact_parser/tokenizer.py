"""
Low-level EDIFACT tokenizer.

Turns raw EDIFACT text into a flat list of Segment objects, handling:
- UNA service string advice (custom delimiters), if present
- component / data-element / segment separators
- the release (escape) character

This layer knows nothing about COPRAR, CODECO, or any specific message type --
it just turns bytes into structured segments. Message-specific meaning is
applied in mapper.py.
"""

from dataclasses import dataclass, field
from typing import List


DEFAULT_DELIMS = {
    "component": ":",
    "element": "+",
    "decimal": ".",
    "release": "?",
    "repetition": "*",
    "segment": "'",
}


@dataclass
class Segment:
    tag: str
    elements: List[List[str]] = field(default_factory=list)

    def element(self, index: int, default=None):
        """Return element at index as a list of components, or default."""
        if 0 <= index < len(self.elements):
            return self.elements[index]
        return default

    def value(self, index: int, component: int = 0, default=None):
        """Convenience: return a single component value as a string."""
        el = self.element(index)
        if el is None or component >= len(el):
            return default
        return el[component]

    def __repr__(self):
        return f"Segment({self.tag}, {self.elements!r})"


def _parse_una(text: str):
    """If text starts with a UNA segment, extract custom delimiters and
    return (delims, remaining_text). Otherwise return (defaults, text)."""
    delims = dict(DEFAULT_DELIMS)
    if text[:3] == "UNA":
        # UNA + 6 delimiter-defining characters, e.g. UNA:+.? *'
        chars = text[3:9]
        delims["component"] = chars[0]
        delims["element"] = chars[1]
        delims["decimal"] = chars[2]
        delims["release"] = chars[3]
        delims["repetition"] = chars[4]
        delims["segment"] = chars[5]
        remaining = text[9:]
        return delims, remaining
    return delims, text


def tokenize(raw: str) -> List[Segment]:
    """Parse a raw EDIFACT interchange into a list of Segment objects."""
    text = raw.strip().replace("\r\n", "").replace("\n", "")
    delims, text = _parse_una(text)

    release = delims["release"]
    seg_sep = delims["segment"]
    el_sep = delims["element"]
    comp_sep = delims["component"]

    # Split on segment separator, but not when it's preceded by the release char.
    raw_segments = _split_respecting_release(text, seg_sep, release)

    segments: List[Segment] = []
    for raw_seg in raw_segments:
        raw_seg = raw_seg.strip()
        if not raw_seg:
            continue
        raw_elements = _split_respecting_release(raw_seg, el_sep, release)
        tag = raw_elements[0]
        elements = []
        for raw_el in raw_elements[1:]:
            components = _split_respecting_release(raw_el, comp_sep, release)
            components = [_unescape(c, release) for c in components]
            elements.append(components)
        segments.append(Segment(tag=tag, elements=elements))

    return segments


def _split_respecting_release(text: str, sep: str, release: str) -> List[str]:
    """Split text on sep, but not when sep is immediately preceded by release."""
    parts = []
    buf = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == release and i + 1 < len(text):
            buf.append(text[i])
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _unescape(component: str, release: str) -> str:
    return component.replace(release + release, release)


def split_messages(segments: List[Segment]):
    """Split a full interchange's segments into per-message (UNH..UNT) chunks.
    Returns a list of (message_type, version, list_of_segments)."""
    messages = []
    current = None
    msg_type = None
    version = None
    for seg in segments:
        if seg.tag == "UNH":
            current = []
            msg_id = seg.element(1) or []
            msg_type = msg_id[0] if len(msg_id) > 0 else None
            version = msg_id[1] if len(msg_id) > 1 else None
            current.append(seg)
        elif seg.tag == "UNT":
            if current is not None:
                current.append(seg)
                messages.append((msg_type, version, current))
            current = None
        elif current is not None:
            current.append(seg)
    return messages
