# Security

Report a vulnerability privately through GitHub's private vulnerability reporting: the repository's Security tab, then "Report a vulnerability". Don't open a public issue for it. Never paste your roxy secrets (`MITMWEB_PASSWORD`, `LAB_SECRET`, the Public Endpoint URL with its secret segment, anything from `~/.config/roxy/`) or a saved session (it holds the traffic you captured) into an issue, a report or a log you share; if a secret leaked, change it in `~/.config/roxy/secrets.env` and restart the lab.
