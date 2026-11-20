"""Client placeholders in `body` and `header` replacements: {proxy_base},
{proxy_base_no_scheme} and {separator}, filled from the client that made the flow,
so a scheme-less URL field can be pointed at the lab without hardcoding its address."""

import re

import pytest
from mitmproxy import http
from mitmproxy.exceptions import OptionsError
from mitmproxy.test import tutils

from chain import (
    LAN_PROXY_BASE,
    LAN_PROXY_BASE_HOST,
    SECRET,
    TUNNEL_HOST,
    TUNNEL_OPTIONS,
    Lab,
    lab_flow,
    run_chain,
    tunnel_flow,
)

SEPARATORS = pytest.mark.parametrize("separator", ["/", "/;"])

MEDIA_HOST_TO_LAB = '''
[[rule]]
name = "cdn through the lab"
filter = "~s & ~d api.example.com"
body = { pattern = 'mediaHost="', replacement = 'mediaHost="{proxy_base_no_scheme}{separator}https://' }
'''


def origin_config():
    return tutils.tresp(
        headers=http.Headers(content_type="application/xml"),
        content=b'<config mediaHost="cdn.example.com/media"/>',
    )


@SEPARATORS
def test_a_body_rule_points_a_scheme_less_url_field_at_the_lab_for_a_lan_client(scenarios, separator):
    flow = lab_flow(f"{separator}https://api.example.com/config.xml")

    run_chain(flow, origin_config(), **scenarios("media-host", MEDIA_HOST_TO_LAB))

    assert flow.response.text == (
        f'<config mediaHost="{LAN_PROXY_BASE_HOST}{separator}https://cdn.example.com/media"/>'
    )


@SEPARATORS
def test_a_body_rule_keeps_the_secret_and_device_slug_for_a_public_endpoint_client(scenarios, separator):
    flow = tunnel_flow(f"/{SECRET}/cloud-device{separator}https://api.example.com/config.xml")
    options = {**TUNNEL_OPTIONS, "lab_origin_allowlist": ["api.example.com"]}

    run_chain(flow, origin_config(), **options, **scenarios("media-host", MEDIA_HOST_TO_LAB))

    assert flow.response.text == (
        f'<config mediaHost="{TUNNEL_HOST}/{SECRET}/cloud-device{separator}https://cdn.example.com/media"/>'
    )


@SEPARATORS
def test_a_header_rule_fills_the_placeholders_too(scenarios, separator):
    options = scenarios("cdn-header", '''
[[rule]]
name = "cdn base through the lab"
filter = "~s & ~d api.example.com"
header = { name = "X-Cdn-Base", value = "{proxy_base}{separator}https://cdn.example.com" }
''')
    flow = lab_flow(f"{separator}https://api.example.com/config.xml")

    run_chain(flow, origin_config(), **options)

    assert flow.response.headers["x-cdn-base"] == f"{LAN_PROXY_BASE}{separator}https://cdn.example.com"


def test_a_ca_routed_flow_has_no_proxy_base_so_a_rule_with_placeholders_leaves_it_alone(scenarios):
    flow = lab_flow("/config.xml", host_header="api.example.com")
    flow.client_conn.tls, flow.client_conn.sni = True, "api.example.com"

    run_chain(flow, origin_config(), lab_ca_routing=True, **scenarios("media-host", MEDIA_HOST_TO_LAB))

    assert flow.response.text == '<config mediaHost="cdn.example.com/media"/>'


@pytest.mark.parametrize("action, unknown", [
    ("""body = { pattern = 'mediaHost="', replacement = 'mediaHost="{proxy_host}/' }""", "{proxy_host}"),
    ('header = { name = "X-Cdn-Base", value = "{proxy_base}{sep}" }', "{sep}"),
])
def test_an_unknown_placeholder_is_refused_at_load_and_the_active_rules_stay(scenarios, action, unknown):
    active = scenarios("media-host", MEDIA_HOST_TO_LAB)
    scenarios("typo", f'[[rule]]\nname = "typo"\nfilter = "~s"\n{action}\n')

    with Lab(**active) as lab:
        with pytest.raises(OptionsError, match=f"unknown placeholder {re.escape(unknown)}"):
            lab.set_options(lab_scenario="typo")
        flow = lab_flow("/https://api.example.com/config.xml")
        lab.run(flow, origin_config())

    assert flow.response.text == f'<config mediaHost="{LAN_PROXY_BASE_HOST}/https://cdn.example.com/media"/>'
    assert "x-cdn-base" not in flow.response.headers


def test_a_broken_edit_with_an_unknown_placeholder_keeps_the_last_good_rules(scenarios):
    options = scenarios("media-host", MEDIA_HOST_TO_LAB)

    with Lab(**options) as lab:
        scenarios("media-host", MEDIA_HOST_TO_LAB.replace("{separator}", "{seperator}"))
        flow = lab_flow("/https://api.example.com/config.xml")
        lab.run(flow, origin_config())

    assert flow.response.text == f'<config mediaHost="{LAN_PROXY_BASE_HOST}/https://cdn.example.com/media"/>'
