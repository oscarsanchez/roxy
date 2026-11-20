"""Text format rewriter: every absolute http(s) URL in any text (HTML, JS, plain text).

The text is never parsed: a URL runs from its scheme to the first character that
cannot be part of it in HTML, JS or CSS (whitespace, a quote, <, >, a parenthesis, a
backslash, or the HTML entity of a quote, < or >), less what the prose around it adds
at its end: sentence punctuation and a closing ] or } it does not open. Everything else
stays byte for byte.
"""

import re

# Entities for the characters a URL stops at: " ' < >, named or numeric.
_STOP_ENTITY = r"&(?:quot|apos|lt|gt|#0*(?:34|39|60|62)|#x0*(?:22|27|3c|3e));"
_URL = re.compile(rf"""(?i:https?)://(?:(?!(?i:{_STOP_ENTITY}))[^\s"'`<>()\\])+""")
_SENTENCE_PUNCTUATION = ".,;:!?"
_OPENING = {"]": "[", "}": "{"}


def _without_prose_end(url):
    """`url` less the sentence punctuation and unopened closing ] or } at its end."""
    end = len(url)
    while end:
        last = url[end - 1]
        unopened = last in _OPENING and url.count(last, 0, end) > url.count(_OPENING[last], 0, end)
        if last not in _SENTENCE_PUNCTUATION and not unopened:
            break
        end -= 1
    return url[:end]


def rewrite_text(text, link):
    """Pass every absolute http(s) URL in the text through `link` (str -> str)."""

    def replace(match):
        url = _without_prose_end(match[0])
        return link(url) + match[0][len(url):]

    return _URL.sub(replace, text)
