"""VAST / generic XML format rewriter: every absolute http(s) URL in the document.

That covers VAST's MediaFile, Impression, Tracking, Error, ClickThrough and
VASTAdTagURI (all CDATA or text), and URLs in any other XML element or attribute.
The text is never parsed, so CDATA, entities and formatting stay byte for byte.
"""

import re

_URL = r"""(?i:https?)://[^\s<>"']+?(?=[\s<>"']|\]\]>|$)"""  # ends before "]]>": VAST macros use [ ]

# Namespace names and schema locations are identifiers, not fetched: kept as they are.
_NAMESPACE_ATTRIBUTE = r"""\b(?:xmlns(?::[\w.-]+)?|[\w.-]+:\w*[sS]chemaLocation)\s*=\s*(?:"[^"]*"|'[^']*')"""

_XML_URLS = re.compile(rf"(?P<keep>{_NAMESPACE_ATTRIBUTE})|(?P<url>{_URL})")


def rewrite_xml(document, link):
    """Pass every absolute URL in the document through `link` (str -> str)."""
    return _XML_URLS.sub(lambda m: m["keep"] or link(m["url"]), document)
