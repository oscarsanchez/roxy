"""DASH format rewriter: URL elements (BaseURL, Location) and segment URL attributes."""

import re

_ELEMENT = re.compile(r"(<(BaseURL|Location)\b[^>]*>)\s*([^<]*?)\s*(</\2>)")
# SegmentTemplate URL templates ($Identifier$s pass through `link` untouched),
# SegmentURL media/index and Initialization/RepresentationIndex sourceURL.
_ATTRIBUTE = re.compile(r'(?<=\s)(media|initialization|index|sourceURL)="([^"]*)"')


def rewrite_dash(manifest, link):
    """Pass every URL in the MPD through `link` (str -> str)."""
    manifest = _ELEMENT.sub(lambda m: f"{m[1]}{link(m[3])}{m[4]}", manifest)
    return _ATTRIBUTE.sub(lambda m: f'{m[1]}="{link(m[2])}"', manifest)


# --- Manifest edits (lab.manifest_edits): MPD text in, edited MPD text out ---

_ADAPTATION_SET = re.compile(r"<AdaptationSet\b.*?</AdaptationSet>", re.S)
# A whole AdaptationSet element with its own line's indentation; group 1 is its attributes.
_WHOLE_ADAPTATION_SET = re.compile(r"[ \t]*<AdaptationSet\b([^>]*)>.*?</AdaptationSet>[ \t]*\n?", re.S)
# A whole Representation element (self-closing or not) with its own line's indentation.
_REPRESENTATION = re.compile(r"[ \t]*<Representation\b([^>]*?)(?:/>|>.*?</Representation>)[ \t]*\n?", re.S)
_XML_ATTRIBUTE = re.compile(r'([\w:.-]+)="([^"]*)"')


def drop_representations(manifest, dropped):
    """Remove each Representation (with its content) for which
    `dropped(attributes, attributes_of_its_adaptation_set_representations)` holds."""

    def in_adaptation_set(match):
        group = [dict(_XML_ATTRIBUTE.findall(r[1])) for r in _REPRESENTATION.finditer(match[0])]
        return _REPRESENTATION.sub(
            lambda r: "" if dropped(dict(_XML_ATTRIBUTE.findall(r[1])), group) else r[0], match[0])

    return _ADAPTATION_SET.sub(in_adaptation_set, manifest)


def drop_adaptation_sets(manifest, dropped):
    """Remove each AdaptationSet (with its content) whose attributes satisfy `dropped`."""
    return _WHOLE_ADAPTATION_SET.sub(
        lambda m: "" if dropped(dict(_XML_ATTRIBUTE.findall(m[1]))) else m[0], manifest)
