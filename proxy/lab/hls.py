"""HLS format rewriter: URI lines and the URI="..." attribute of any tag."""

import re

_URI_ATTRIBUTE = re.compile(r'(?<=[:,])URI="([^"]*)"')


def rewrite_hls(playlist, link):
    """Pass every URI in the playlist through `link` (str -> str)."""
    return "".join(_rewrite_line(line, link) for line in playlist.splitlines(keepends=True))


def _rewrite_line(line, link):
    if line.startswith("#"):
        return _URI_ATTRIBUTE.sub(lambda m: f'URI="{link(m[1])}"', line)
    uri = line.strip()
    return line.replace(uri, link(uri), 1) if uri else line


# --- Manifest edits (lab.manifest_edits): playlist text in, edited playlist text out ---

_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def attributes(tag_line):
    """The attribute list of a tag line, as a dict with the quotes removed."""
    return {name: value.strip('"') for name, value in _ATTRIBUTE.findall(tag_line.partition(":")[2])}


def is_uri_line(line):
    return bool(line.strip()) and not line.startswith("#")


def drop_variants(playlist, dropped):
    """Remove each variant for which `dropped(attributes, all_variants_attributes)`
    holds: its EXT-X-STREAM-INF tag and the URI line after it. I-frame variants
    are left alone."""
    lines = playlist.splitlines(keepends=True)
    group = [attributes(line) for line in lines if line.startswith("#EXT-X-STREAM-INF:")]
    out, dropping = [], False
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            dropping = dropped(attributes(line), group)
        elif dropping and is_uri_line(line):
            dropping = False
            continue
        if not dropping:
            out.append(line)
    return "".join(out)


def drop_renditions(playlist, dropped):
    """Remove each rendition (EXT-X-MEDIA tag) whose attributes satisfy `dropped`."""
    return "".join(
        line for line in playlist.splitlines(keepends=True)
        if not (line.startswith("#EXT-X-MEDIA:") and dropped(attributes(line)))
    )


_SEGMENT_TAGS = ("#EXTINF:", "#EXT-X-BYTERANGE:", "#EXT-X-PROGRAM-DATE-TIME:")  # this segment's only


def edit_segments(playlist, edit):
    """Pass each segment of a media playlist through `edit(index, lines) -> lines`
    (index from 0). A segment's lines run from after the previous segment's URI
    line to its own, so they can hold tags that also apply to later segments
    (EXT-X-KEY, EXT-X-MAP, ...). A master playlist is returned as it is."""
    if "#EXTINF:" not in playlist:
        return playlist
    out, segment, index = [], [], 0
    for line in playlist.splitlines(keepends=True):
        segment.append(line)
        if is_uri_line(line):
            out += edit(index, segment)
            segment, index = [], index + 1
    return "".join(out + segment)


def drop_segment(lines):
    """A removed segment: only the tags that also apply to later segments stay."""
    return [line for line in lines if not (is_uri_line(line) or line.startswith(_SEGMENT_TAGS))]


def alter_segment(lines, uri=None, duration=None):
    """A segment with its URI and/or its EXTINF duration replaced (None keeps it)."""

    def altered(line):
        if uri is not None and is_uri_line(line):
            return line.replace(line.strip(), uri, 1)
        if duration is not None and line.startswith("#EXTINF:"):
            return re.sub(r"(?<=^#EXTINF:)[^,\r\n]*", str(duration), line)
        return line

    return [altered(line) for line in lines]
