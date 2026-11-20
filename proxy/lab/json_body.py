"""JSON format rewriter: string values that are absolute http(s) URLs.

Works on the text, token by token, so everything else (keys, numbers, spacing,
escapes, other strings) reaches the client exactly as the Origin sent it.
"""

import json
import re

# Every string literal, plus the colon that makes it an object key. Outside
# strings, JSON has no quote characters, so a left-to-right scan finds them all.
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"(\s*:)?')
_ABSOLUTE = re.compile(r"https?://", re.IGNORECASE)


def rewrite_json(document, link):
    """Pass every absolute http(s) URL string value through `link` (str -> str)."""
    return _STRING.sub(lambda m: _rewrite_string(m, link), document)


def _rewrite_string(match, link):
    if match[1] is not None:  # an object key, not a value
        return match[0]
    try:
        value = json.loads(match[0], strict=False)
    except ValueError:  # not valid JSON: leave it to the client
        return match[0]
    if not _ABSOLUTE.match(value):
        return match[0]
    return json.dumps(link(value), ensure_ascii=False)
