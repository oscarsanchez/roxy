import socket

import pytest

PUBLIC_IP = "93.184.215.14"


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Stubbed DNS: every host resolves to a public IP unless a test sets
    dns[host] = [ip, ...]; an empty list means the host does not resolve.
    Covers loop.getaddrinfo too (it calls socket.getaddrinfo)."""
    answers = {}

    def getaddrinfo(host, port, *args, **kwargs):
        if answers.get(host) == []:
            raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known")
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))
            if ":" in ip
            else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
            for ip in answers.get(host, [PUBLIC_IP])
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return answers
