"""Text format rewriter: every absolute http(s) URL in any text (HTML, JS, plain text).

The text is never parsed: a URL runs from its scheme to the first character that
cannot be part of it in HTML, JS or CSS (whitespace, a quote, <, >, a parenthesis
or a backslash), and everything else stays byte for byte.
"""

import re

_URL = re.compile(r"""(?i:https?)://[^\s"'`<>()\\]+""")


def rewrite_text(text, link):
    """Pass every absolute http(s) URL in the text through `link` (str -> str)."""
    return _URL.sub(lambda m: link(m[0]), text)
