"""mitmweb entry script (`mitmweb -s proxy/entry.py`): loads the lab addon chain."""

from lab import addon_chain

addons = addon_chain()
