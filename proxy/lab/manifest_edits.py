"""Manifest-edit scenario actions: edit HLS playlists and DASH MPDs on their way
to the client.

Each factory takes a rule's action value (validated here) and returns a
ManifestEdit; they are registered in scenario_actions.ACTIONS. The Scenarios
addon is last in the chain, so edits see the manifest after body rewriting: the
URIs that remain are already Prefixed URLs and still route through the lab, and
a URI an edit puts in goes through the body rewriter's `lab_link` as well.

Only manifests are edited: the format is the one the BodyRewriter chose
(flow.metadata["body_format"], from its lab_rewrite_<format> options), so a broad
filter never touches segments or other bodies. drop_variants and drop_renditions
cover HLS and DASH; the segment edits are HLS only (a DASH SegmentTemplate has
no per-segment entries to edit).
"""

from typing import NamedTuple

from lab import dash, hls
from lab.body_rewriting import lab_link


class ManifestEdit:
    """Each edit is `(manifest text, link) -> manifest text`; None leaves that format alone."""

    def __init__(self, edit_hls, edit_dash=None):
        self.edits = {"hls": edit_hls, "dash": edit_dash}  # by BodyFormat.name

    def response(self, flow):
        edit = self.edits.get(flow.metadata.get("body_format"))  # as the BodyRewriter chose it
        if edit is None:
            return
        manifest = flow.response.text
        edited = edit(manifest, lab_link(flow))
        if edited != manifest:
            flow.response.text = edited


def drop_variants(value, scenario_dir):
    """Drop HLS variants (EXT-X-STREAM-INF; I-frame ones are left alone) and DASH
    Representations by one criterion: `{ bandwidth_above = bps }`,
    `{ bandwidth_below = bps }`, `{ resolution = "WxH" }`, or
    `{ all_but = "lowest" | "highest" }` by bandwidth, equal ones all kept. For
    `all_but`, an HLS master is one group and each DASH AdaptationSet is its own."""
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("drop_variants needs one of bandwidth_above, bandwidth_below, resolution, all_but")
    [(key, arg)] = value.items()
    if key == "bandwidth_above" and type(arg) is int:
        return variants_dropped_where(lambda v, group: v.bandwidth > arg)
    if key == "bandwidth_below" and type(arg) is int:
        return variants_dropped_where(lambda v, group: v.bandwidth < arg)
    if key == "resolution" and isinstance(arg, str):
        return variants_dropped_where(lambda v, group: v.resolution == arg)
    if key == "all_but" and arg in ("lowest", "highest"):
        pick = min if arg == "lowest" else max
        return variants_dropped_where(lambda v, group: v.bandwidth != pick(g.bandwidth for g in group))
    raise ValueError(f"drop_variants: bad criterion {key} = {arg!r}")


class Variant(NamedTuple):
    """An HLS variant or a DASH Representation, as drop_variants compares them."""
    bandwidth: int
    resolution: str | None  # "WxH"


def hls_variant(attributes):
    return Variant(number(attributes.get("BANDWIDTH")), attributes.get("RESOLUTION"))


def dash_variant(attributes):
    width, height = attributes.get("width"), attributes.get("height")
    return Variant(number(attributes.get("bandwidth")), f"{width}x{height}" if width and height else None)


def number(value):
    return int(value) if value and value.isdigit() else 0


def variants_dropped_where(dropped):
    """A ManifestEdit dropping each variant for which `dropped(variant, group)` holds."""

    def edit(format_drop, variant):
        return lambda manifest, link: format_drop(
            manifest, lambda v, group: dropped(variant(v), [variant(g) for g in group]))

    return ManifestEdit(edit(hls.drop_variants, hls_variant), edit(dash.drop_representations, dash_variant))


# A rendition rule's keys, per format, and the attribute each one matches.
HLS_RENDITION_KEYS = {"type": "TYPE", "group_id": "GROUP-ID", "language": "LANGUAGE", "name": "NAME"}  # EXT-X-MEDIA
DASH_RENDITION_KEYS = {"content_type": "contentType", "mime_type": "mimeType", "lang": "lang"}  # AdaptationSet


def drop_renditions(value, scenario_dir):
    """Drop renditions that match every given attribute, with the keys of one format:
    HLS EXT-X-MEDIA tags (`{ type = "AUDIO", language = "en" }`; type, group_id,
    language, name) or DASH AdaptationSets (`{ content_type = "audio" }`;
    content_type, mime_type, lang). The other format is left alone."""
    if (not isinstance(value, dict) or not value or not all(isinstance(v, str) for v in value.values())
            or not (set(value) <= set(HLS_RENDITION_KEYS) or set(value) <= set(DASH_RENDITION_KEYS))):
        raise ValueError(
            "drop_renditions must be { ... } of strings, keys from one format: "
            f"HLS {', '.join(HLS_RENDITION_KEYS)} or DASH {', '.join(DASH_RENDITION_KEYS)}")

    def for_format(keys, format_drop):
        if not set(value) <= set(keys):
            return None  # the other format's rule
        wanted = {keys[key]: arg for key, arg in value.items()}
        return lambda manifest, link: format_drop(
            manifest, lambda attributes: all(attributes.get(name) == arg for name, arg in wanted.items()))

    return ManifestEdit(for_format(HLS_RENDITION_KEYS, hls.drop_renditions),
                        for_format(DASH_RENDITION_KEYS, dash.drop_adaptation_sets))


def drop_segments(value, scenario_dir):
    """Remove segments from HLS media playlists: `{ from = N, to = M }`, indexes
    from 0, `to` included; without `to`, up to the end."""
    selected = segment_range(value, "drop_segments", ())
    return ManifestEdit(lambda playlist, link: hls.edit_segments(
        playlist, lambda i, lines: hls.drop_segment(lines) if selected(i) else lines))


def alter_segments(value, scenario_dir):
    """Alter segments of HLS media playlists: `{ from = N, to = M, uri = "...",
    duration = seconds }` (`to` as for drop_segments; uri and/or duration).
    A relative uri resolves against the playlist's Prefixed URL; an absolute one
    is made a Prefixed URL, so either way it reaches the lab."""
    selected = segment_range(value, "alter_segments", ("uri", "duration"))
    uri, duration = value.get("uri"), value.get("duration")
    if (uri is None and duration is None or not (uri is None or isinstance(uri, str))
            or not (duration is None or type(duration) in (int, float) and duration >= 0)):
        raise ValueError("alter_segments needs a uri (string) and/or a duration (seconds >= 0)")

    def edit(playlist, link):
        new_uri = None if uri is None else link(uri)
        return hls.edit_segments(
            playlist, lambda i, lines: hls.alter_segment(lines, new_uri, duration) if selected(i) else lines)

    return ManifestEdit(edit)


def segment_range(value, action, options):
    """Validate `{ from = N, to = M, <options> }`; returns `selected(index) -> bool`."""
    if not isinstance(value, dict) or "from" not in value or not set(value) <= {"from", "to", *options}:
        raise ValueError(f"{action} must be {{ from = N, to = M (optional){''.join(f', {o} = ...' for o in options)} }}")
    first, last = value["from"], value.get("to")
    if type(first) is not int or first < 0 or not (last is None or (type(last) is int and last >= first)):
        raise ValueError(f"{action}: from and to must be segment indexes, from 0, with from <= to")
    return lambda index: first <= index and (last is None or index <= last)


ACTIONS = {
    "drop_variants": drop_variants,
    "drop_renditions": drop_renditions,
    "drop_segments": drop_segments,
    "alter_segments": alter_segments,
}
