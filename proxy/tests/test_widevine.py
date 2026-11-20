"""Widevine: the license request travels through the lab as a Prefixed URL, untouched."""

from mitmproxy import http
from mitmproxy.test import tutils

from chain import lab_flow, run_chain


LICENSE_URL = "https://proxy.uat.widevine.com/proxy?provider=widevine_test"
CHALLENGE = bytes(range(256))  # binary, as the CDM sends it
LICENSE = bytes(reversed(range(256)))


def license_request():
    flow = lab_flow(f"/{LICENSE_URL}")
    flow.request.method = "POST"
    flow.request.headers["content-type"] = "text/plain"  # Roku's default for license requests
    flow.request.content = CHALLENGE
    return flow


def license_response():
    return tutils.tresp(headers=http.Headers(content_type="application/octet-stream"), content=LICENSE)


def test_the_license_challenge_and_license_pass_through_byte_for_byte():
    flow = license_request()

    forwarded = run_chain(flow, license_response())

    assert forwarded.method == "POST"
    assert forwarded.url == LICENSE_URL
    assert forwarded.content == CHALLENGE
    assert flow.response.status_code == 200
    assert flow.response.content == LICENSE


def test_the_widevine_license_fail_scenario_fails_only_the_license_request():
    failed = license_request()
    manifest = lab_flow("/https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears_sd.mpd")

    run_chain(failed, license_response(), lab_scenario="widevine-license-fail")
    run_chain(manifest, tutils.tresp(content=b"<MPD/>"), lab_scenario="widevine-license-fail")

    assert failed.response.status_code == 403
    assert manifest.response.status_code == 200
