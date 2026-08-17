"""Wave 2 video-plane infrastructure gate (SAATHI-451, frozen matrix row H1).

WHAT THIS FILE CAN AND CANNOT PROVE. Every assertion here is STATIC: the compose
files parse, the images are pinned, the ports do not collide, no secret literal
is committed, the environment variable NAMES are exactly the ones
``app.core.config.Settings`` and ``LiveKitCommunityAdapter`` read, the webhook URL
is exactly the route the committed handler is mounted at, and the forced-TURN
posture (no published SFU media ports, a hard-coded internal ``node_ip``, a
single-destination TURN peer ACL) is actually expressed in the files.

It does NOT start a server, join a room, relay a packet or observe a reconnect.
Those are runtime checks; they are enumerated as UNEXECUTED /
ENVIRONMENT-BLOCKED in ``infra/video/RUNBOOK.md`` § 9 with the exact operator
command and expected observable for each. Nothing in this module may be cited as
evidence for any of them.

Why the checks live in the test suite rather than a lint script: every one of
them is a claim about the relationship between the INFRA and the COMMITTED CODE
(a Settings field name, a route path, an adapter's placeholder-rejection set), so
they must break in the same run that breaks the code they are pinned to.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from app.core.config import (
    _PLACEHOLDER_SECRETS,
    Settings,
    _is_placeholder_secret,
)
from app.services.providers.video_provider import (
    LiveKitCommunityAdapter,
    VideoProviderError,
)

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "infra" / "video"
ROOT_COMPOSE = REPO / "docker-compose.yml"
BACKEND_DOCKERFILE = REPO / "docker" / "backend.Dockerfile"
BASE_COMPOSE = INFRA / "docker-compose.video.yml"
DIRECT_COMPOSE = INFRA / "docker-compose.video.direct.yml"
ENV_EXAMPLE = INFRA / ".env.example"
SBOM = INFRA / "SBOM.md"
RUNBOOK = INFRA / "RUNBOOK.md"
RENDERER = REPO / "scripts" / "render_video_infra_config.py"
TEMPLATES = {
    "forced-turn": INFRA / "livekit.forced-turn.yaml.tmpl",
    "direct": INFRA / "livekit.direct.yaml.tmpl",
}
TURN_TEMPLATE = INFRA / "turnserver.conf.tmpl"

#: The SFU's fixed address on the private ``video`` network. Three files have to
#: agree on it: the compose static IP, the forced-turn template's ``node_ip`` and
#: coturn's ``allowed-peer-ip``. That agreement is the whole forced-TURN posture.
SFU_STATIC_IP = "172.29.31.10"
TURN_STATIC_IP = "172.29.31.11"
RELAY_RANGE = (21500, 21549)

#: Host ports the video plane is allowed to take, and which overlay takes them.
BASE_HOST_PORTS = {1139, 1142, 1143} | set(range(RELAY_RANGE[0], RELAY_RANGE[1] + 1))
DIRECT_HOST_PORTS = {1140, 1141}

#: Names the BACKEND reads. Uppercased ``Settings`` field names — pydantic-settings
#: maps them 1:1, so a typo here is a setting that silently keeps its default.
BACKEND_ENV_NAMES = (
    "VIDEO_CALLS_ENABLED",
    "VIDEO_PROVIDER",
    "LIVEKIT_URL",
    "LIVEKIT_PUBLIC_URL",
    "VIDEO_ICE_TRANSPORT_POLICY",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "JOIN_CREDENTIAL_TTL_SECONDS",
)
#: Names ONLY the infra reads. Asserted NOT to be Settings fields so nobody
#: believes the application honours them.
INFRA_ONLY_ENV_NAMES = (
    "TURN_PUBLIC_HOST",
    "TURN_PUBLIC_PORT",
    "TURN_REALM",
    "TURN_EXTERNAL_IP",
    "TURN_STATIC_AUTH_SECRET",
    "TURN_CREDENTIAL_TTL_SECONDS",
    "VIDEO_WEBHOOK_URL",
    "LIVEKIT_ADVERTISE_IP",
)

#: A value assigned to a name that looks like a credential must be one of these
#: shapes. Anything else is a committed secret.
_SECRETISH_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z0-9_.\-]*(?:secret|password|passwd|api_key|token|credential)"
    r"[a-z0-9_.\-]*)\s*[:=]\s*(\S+)"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_backend_image_copies_the_lockfile_required_by_requirements_txt():
    """A clean container build must not depend on a host-only lockfile.

    ``requirements.txt`` includes ``-r requirements.lock``. Copying only the
    first file makes Docker fail before the application can start, which in
    turn makes every LiveKit/TURN runtime check impossible.
    """
    requirements = (REPO / "backend" / "requirements.txt").read_text(encoding="utf-8")
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "requirements.lock" in requirements
    assert re.search(
        r"^COPY\s+backend/requirements\.txt\s+backend/requirements\.lock\s+\./$",
        dockerfile,
        re.MULTILINE,
    )
    assert "RUN pip install --no-cache-dir -r requirements.txt" in dockerfile


def test_video_config_mounts_are_root_compose_relative_files_not_directories():
    """Compose resolves relative bind paths from the first/root compose file."""
    compose = _load(BASE_COMPOSE)
    livekit_volumes = compose["services"]["livekit"]["volumes"]
    coturn_volumes = compose["services"]["coturn"]["volumes"]
    assert any(
        str(v).startswith("./infra/video/rendered/livekit.yaml:")
        for v in livekit_volumes
    )
    assert any(
        str(v).startswith("./infra/video/rendered/turnserver.conf:")
        for v in coturn_volumes
    )
    assert not any(str(v).startswith("./rendered/") for v in livekit_volumes + coturn_volumes)


def _renderer():
    """Import the deploy-time renderer by path (it is not an installed module)."""
    spec = importlib.util.spec_from_file_location("_ls_video_renderer", RENDERER)
    assert spec and spec.loader, RENDERER
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_port_entry(entry: str) -> set[int]:
    """``"1143:3478/udp"`` -> ``{1143}``; ``"21500-21549:...`` -> the whole range."""
    host = str(entry).split(":")[0]
    host = host.split("/")[0]
    if "-" in host:
        low, _, high = host.partition("-")
        return set(range(int(low), int(high) + 1))
    return {int(host)}


def _service_host_ports(compose: dict) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for name, service in (compose.get("services") or {}).items():
        ports: set[int] = set()
        for entry in service.get("ports") or []:
            ports |= _parse_port_entry(entry)
        out[name] = ports
    return out


def _images(compose: dict) -> dict[str, str]:
    return {
        name: service["image"]
        for name, service in (compose.get("services") or {}).items()
        if "image" in service
    }


def _env_example() -> dict[str, str]:
    return _renderer().load_env_file(ENV_EXAMPLE)


def _committed_files() -> list[Path]:
    """Every file in infra/video that git tracks (i.e. excludes rendered/)."""
    return sorted(
        p
        for p in INFRA.rglob("*")
        if p.is_file() and "rendered" not in p.relative_to(INFRA).parts
    )


def _base_env(**overrides: str) -> dict[str, str]:
    """A realistic, obviously-fake environment. Nothing here is a credential."""
    env = {
        "LIVEKIT_API_KEY": "APIunitTestKeyValue",
        "LIVEKIT_API_SECRET": "0123456789abcdef0123456789abcdef",
        "TURN_PUBLIC_HOST": "turn.unit-test.invalid",
        "TURN_PUBLIC_PORT": "1143",
        "TURN_REALM": "turn.unit-test.invalid",
        "TURN_EXTERNAL_IP": "203.0.113.10",
        "TURN_STATIC_AUTH_SECRET": "fedcba9876543210fedcba9876543210",
        "TURN_CREDENTIAL_TTL_SECONDS": "3600",
        "VIDEO_WEBHOOK_URL": "http://backend:1031/api/v1/video/webhook",
        "LIVEKIT_ADVERTISE_IP": "203.0.113.11",
    }
    env.update(overrides)
    return env


# --------------------------------------------------------------------------- #
# the files exist and parse
# --------------------------------------------------------------------------- #


def test_every_declared_infra_file_exists():
    for path in (
        BASE_COMPOSE, DIRECT_COMPOSE, ENV_EXAMPLE, SBOM, RUNBOOK, RENDERER,
        TURN_TEMPLATE, INFRA / "README.md", *TEMPLATES.values(),
    ):
        assert path.is_file(), f"missing infra file: {path}"


def test_compose_overlays_parse_as_yaml():
    for path in (BASE_COMPOSE, DIRECT_COMPOSE):
        parsed = _load(path)
        assert isinstance(parsed, dict), path
        assert parsed.get("services"), f"{path} declares no services"


def test_base_overlay_declares_both_services_under_the_video_profile():
    services = _load(BASE_COMPOSE)["services"]
    assert set(services) == {"livekit", "coturn"}
    for name, service in services.items():
        # Without the profile, `docker compose up` would start the media plane
        # for every developer running the existing dev stack.
        assert service.get("profiles") == ["video"], name


# --------------------------------------------------------------------------- #
# images are pinned
# --------------------------------------------------------------------------- #

_PINNED = re.compile(r"^[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def test_images_are_pinned_by_tag_and_digest():
    images = _images(_load(BASE_COMPOSE))
    assert set(images) == {"livekit", "coturn"}
    for service, ref in images.items():
        assert _PINNED.match(ref), f"{service}: not tag+digest pinned: {ref}"
        assert ":latest@" not in ref and not ref.endswith(":latest"), service


def test_no_latest_tag_anywhere_under_infra_video():
    for path in _committed_files():
        if path.suffix in {".md"}:
            continue  # prose may legitimately mention the word
        text = path.read_text(encoding="utf-8")
        assert ":latest" not in text, f"{path} pins a moving tag"


def test_sbom_records_exactly_the_pinned_images():
    sbom = SBOM.read_text(encoding="utf-8")
    for ref in _images(_load(BASE_COMPOSE)).values():
        tagged, _, digest = ref.partition("@")
        assert f"`{tagged}`" in sbom, f"SBOM does not list {tagged}"
        assert digest in sbom, f"SBOM digest disagrees with compose for {tagged}"


# --------------------------------------------------------------------------- #
# ports
# --------------------------------------------------------------------------- #


def test_video_host_ports_do_not_collide_with_the_root_compose_stack():
    root_ports: set[int] = set()
    for ports in _service_host_ports(_load(ROOT_COMPOSE)).values():
        root_ports |= ports
    # Sanity: the fixture we are comparing against is the real thing.
    assert {1130, 1131, 1132, 1138} <= root_ports

    video_ports: set[int] = set()
    for compose in (BASE_COMPOSE, DIRECT_COMPOSE):
        for ports in _service_host_ports(_load(compose)).values():
            video_ports |= ports
    assert not (video_ports & root_ports), (
        "video plane collides with an existing service on "
        f"{sorted(video_ports & root_ports)}"
    )


def test_video_host_ports_are_exactly_the_documented_allocation():
    base = _service_host_ports(_load(BASE_COMPOSE))
    assert base["livekit"] == {1139, 1142}
    assert base["coturn"] == {1143} | set(
        range(RELAY_RANGE[0], RELAY_RANGE[1] + 1)
    )
    direct = _service_host_ports(_load(DIRECT_COMPOSE))
    assert direct["livekit"] == DIRECT_HOST_PORTS
    assert not (BASE_HOST_PORTS & DIRECT_HOST_PORTS)


def test_root_compose_header_records_the_video_port_reservation():
    """The root compose header is the repo's single source of truth for ports."""
    header = ROOT_COMPOSE.read_text(encoding="utf-8").split("services:")[0]
    for port in (1139, 1140, 1141, 1142, 1143, 1144):
        assert str(port) in header, f"port {port} is not reserved in {ROOT_COMPOSE}"
    assert f"{RELAY_RANGE[0]}-{RELAY_RANGE[1]}" in header


def test_coturn_publishes_the_relay_range_the_config_actually_uses():
    conf = TURN_TEMPLATE.read_text(encoding="utf-8")
    assert f"min-port={RELAY_RANGE[0]}" in conf
    assert f"max-port={RELAY_RANGE[1]}" in conf
    published = _service_host_ports(_load(BASE_COMPOSE))["coturn"]
    assert set(range(RELAY_RANGE[0], RELAY_RANGE[1] + 1)) <= published, (
        "coturn allocates relay ports docker does not publish; every allocation "
        "outside the published block is a call that connects and then has no media"
    )


# --------------------------------------------------------------------------- #
# health and readiness
# --------------------------------------------------------------------------- #


def test_both_services_declare_a_healthcheck_with_the_house_knobs():
    for name, service in _load(BASE_COMPOSE)["services"].items():
        check = service.get("healthcheck")
        assert check, f"{name} has no healthcheck"
        assert check.get("test"), name
        # Same knobs the root compose file uses for postgres.
        assert check.get("interval") == "5s", name
        assert check.get("timeout") == "3s", name
        assert check.get("retries") == 10, name


def test_healthchecks_probe_the_protocol_not_just_a_socket():
    services = _load(BASE_COMPOSE)["services"]
    livekit_probe = " ".join(services["livekit"]["healthcheck"]["test"])
    # LiveKit's own Helm chart probes GET / on the signalling port.
    assert "7880" in livekit_probe and "http://" in livekit_probe
    coturn_probe = " ".join(services["coturn"]["healthcheck"]["test"])
    # A real STUN Binding transaction, not `nc -z`.
    assert "turnutils_stunclient" in coturn_probe
    assert "3478" in coturn_probe


def test_livekit_waits_for_a_healthy_relay():
    """LiveKit hands the TURN address to every client; it must be answering."""
    depends = _load(BASE_COMPOSE)["services"]["livekit"]["depends_on"]
    assert depends["coturn"]["condition"] == "service_healthy"


def test_prometheus_readiness_target_is_published():
    livekit = _load(BASE_COMPOSE)["services"]["livekit"]
    assert "1142:6789" in [str(p) for p in livekit["ports"]]
    for template in TEMPLATES.values():
        assert "prometheus_port: 6789" in template.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# forced-TURN posture
# --------------------------------------------------------------------------- #


def test_base_overlay_publishes_no_sfu_media_port():
    """The mechanism: with 7881/7882 unpublished, the relay is the only route."""
    for entry in _load(BASE_COMPOSE)["services"]["livekit"]["ports"]:
        assert "7881" not in str(entry) and "7882" not in str(entry), entry


def test_direct_overlay_is_the_only_thing_that_opens_direct_media():
    entries = [str(p) for p in _load(DIRECT_COMPOSE)["services"]["livekit"]["ports"]]
    assert entries == ["1140:1140", "1141:1141/udp"]


def test_forced_turn_template_hardcodes_the_internal_node_ip():
    """The multi-homed SFU must use only the peer address coturn permits."""
    text = TEMPLATES["forced-turn"].read_text(encoding="utf-8")
    assert f"node_ip: {SFU_STATIC_IP}" in text
    assert "node_ip: ${" not in text
    assert "use_external_ip: false" in text
    rendered = _renderer().render("forced-turn", _base_env())["livekit"][1]
    config = yaml.safe_load(rendered)
    assert config["rtc"]["ips"]["includes"] == [f"{SFU_STATIC_IP}/32"]


def test_direct_template_requires_an_operator_supplied_advertise_ip():
    text = TEMPLATES["direct"].read_text(encoding="utf-8")
    assert "node_ip: ${LIVEKIT_ADVERTISE_IP}" in text


def test_compose_static_ips_match_what_the_configs_pin():
    services = _load(BASE_COMPOSE)["services"]
    assert services["livekit"]["networks"]["video"]["ipv4_address"] == SFU_STATIC_IP
    assert services["coturn"]["networks"]["video"]["ipv4_address"] == TURN_STATIC_IP
    subnet = _load(BASE_COMPOSE)["networks"]["video"]["ipam"]["config"][0]["subnet"]
    assert subnet == "172.29.31.0/24"


def test_turn_peer_acl_allows_the_sfu_and_nothing_else():
    lines = [
        line.strip()
        for line in TURN_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    denied = [line for line in lines if line.startswith("denied-peer-ip=")]
    allowed = [line for line in lines if line.startswith("allowed-peer-ip=")]
    assert denied == ["denied-peer-ip=0.0.0.0-255.255.255.255"]
    assert allowed == [f"allowed-peer-ip={SFU_STATIC_IP}"]
    # coturn's explicit allow rule overrides the blanket deny for this SFU peer.


def test_coturn_advertises_the_operator_supplied_relay_address():
    """Browser candidate is public; coturn discovers its private relay socket."""
    lines = {
        line.strip()
        for line in _render("forced-turn")["coturn_text"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert f"external-ip={_base_env()['TURN_EXTERNAL_IP']}" in lines
    assert not any(line.startswith("relay-ip=") for line in lines)


def test_turn_uses_rest_credentials_and_holds_no_static_secret():
    text = TURN_TEMPLATE.read_text(encoding="utf-8")
    assert "use-auth-secret" in text
    body = [
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # The shared secret arrives on the command line, never in this file: coturn
    # runs as `nobody` and cannot read a 0600 file, so the file must stay
    # secret-free to be safe at 0644.
    assert not any(line.startswith("static-auth-secret") for line in body)
    compose_cmd = " ".join(_load(BASE_COMPOSE)["services"]["coturn"]["command"])
    assert "--static-auth-secret=${TURN_STATIC_AUTH_SECRET" in compose_cmd


def test_neither_template_leaks_clients_to_a_third_party_stun_server():
    """An empty ``stun_servers`` list makes LiveKit clients use Google's STUN.

    Asserted on the RENDERED config, so a third-party host mentioned in a comment
    (the templates explain exactly this hazard) cannot fail the check and, more
    importantly, cannot pass it either.
    """
    for mode in TEMPLATES:
        rtc = _render(mode)["livekit"]["rtc"]
        assert rtc["stun_servers"], mode
        hosts = [str(s) for s in rtc["stun_servers"]] + [
            str(s["host"]) for s in rtc["turn_servers"]
        ]
        for host in hosts:
            assert host.startswith(_base_env()["TURN_PUBLIC_HOST"]), (mode, host)


def test_embedded_livekit_turn_stays_off_in_both_modes():
    for mode, template in TEMPLATES.items():
        rendered = _render(mode)
        assert rendered["livekit"]["turn"]["enabled"] is False, mode


# --------------------------------------------------------------------------- #
# environment variable names match the committed code
# --------------------------------------------------------------------------- #


def test_backend_env_names_are_real_settings_fields():
    fields = set(Settings.model_fields)
    for name in BACKEND_ENV_NAMES:
        assert name.lower() in fields, (
            f"{name} is not a Settings field; pydantic-settings would ignore it "
            "and the setting would silently keep its default"
        )


def test_infra_only_env_names_are_not_settings_fields():
    fields = set(Settings.model_fields)
    for name in INFRA_ONLY_ENV_NAMES:
        assert name.lower() not in fields, (
            f"{name} looks like a backend setting but is infra-only"
        )


def test_env_example_declares_every_name_and_nothing_undocumented():
    declared = set(_env_example())
    assert declared == set(BACKEND_ENV_NAMES) | set(INFRA_ONLY_ENV_NAMES), (
        "infra/video/.env.example drifted from the documented variable set: "
        f"{sorted(declared.symmetric_difference(set(BACKEND_ENV_NAMES) | set(INFRA_ONLY_ENV_NAMES)))}"
    )


def test_env_example_secrets_are_placeholders_the_app_actively_rejects():
    values = _env_example()
    for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "TURN_STATIC_AUTH_SECRET"):
        assert _is_placeholder_secret(values[name]), (
            f"{name} in .env.example is not a recognised placeholder — a copied "
            "template would boot instead of failing closed"
        )


def test_env_example_cannot_switch_a_deployment_onto_livekit_by_accident():
    values = _env_example()
    assert values["VIDEO_CALLS_ENABLED"] == "false"
    assert values["VIDEO_PROVIDER"] == "none"


def test_env_example_separates_server_and_browser_livekit_urls():
    values = _env_example()
    assert values["LIVEKIT_URL"].startswith(("http://", "https://"))
    assert values["LIVEKIT_PUBLIC_URL"].startswith(("ws://", "wss://"))


def test_env_example_livekit_url_uses_a_scheme_httpx_can_post_to():
    """LiveKitCommunityAdapter._twirp POSTs to {LIVEKIT_URL}/twirp/... via httpx.

    A ``wss://`` value passes every configuration check and then fails every
    server-side call at runtime, so the template must not model one.
    """
    url = _env_example()["LIVEKIT_URL"]
    assert url.startswith(("http://", "https://")), url


def test_env_example_ttl_matches_the_settings_default():
    assert int(_env_example()["JOIN_CREDENTIAL_TTL_SECONDS"]) == (
        Settings(_env_file=None).join_credential_ttl_seconds
    )


# --------------------------------------------------------------------------- #
# webhook wiring matches the committed route
# --------------------------------------------------------------------------- #


def test_webhook_url_is_the_route_the_committed_handler_is_mounted_at():
    from app.api.v1 import tutoring as ep

    paths = {getattr(route, "path", None) for route in ep.router.routes}
    assert "/video/webhook" in paths, sorted(p for p in paths if p)
    # The router is mounted under /api/v1 by app.api.v1.router / app.main.
    expected = "/api/v1/video/webhook"
    url = _env_example()["VIDEO_WEBHOOK_URL"]
    assert url.endswith(expected), url
    for mode in TEMPLATES:
        assert _render(mode)["livekit"]["webhook"]["urls"] == [
            _base_env()["VIDEO_WEBHOOK_URL"]
        ]
    assert _renderer().WEBHOOK_PATH == expected


def test_webhook_signing_key_is_one_of_the_declared_api_keys():
    """LiveKit refuses to start a notifier for a key it does not hold."""
    for mode in TEMPLATES:
        config = _render(mode)["livekit"]
        assert config["webhook"]["api_key"] in config["keys"]


def test_webhook_is_filtered_to_the_event_types_the_adapter_maps():
    from app.services.providers.video_provider import VIDEO_EVENT_TYPES

    for mode in TEMPLATES:
        included = _render(mode)["livekit"]["webhook"]["filter_params"][
            "include_events"
        ]
        assert set(included) == set(VIDEO_EVENT_TYPES), mode


def test_livekit_adapter_still_fails_closed_on_an_unsigned_delivery():
    """Locks in the SAFE half of the webhook path — unchanged by the transport fix.

    The adapter now verifies what a real LiveKit server actually sends (a signed
    JWT in ``Authorization``; see
    ``LiveKitCommunityAdapter._verify_webhook_token`` and
    ``tests/test_wave2_video_webhook_livekit.py`` for the positive case). This test
    keeps pinning the property that must hold whatever the transport is: a
    delivery presenting no credential, or garbage in place of one, is REFUSED —
    fail-closed and non-retryable — so an unverified event can never be admitted.
    """
    adapter = LiveKitCommunityAdapter(
        "http://livekit.invalid:7880",
        "APIunitTestKeyValue",
        "0123456789abcdef0123456789abcdef",
    )
    body = b'{"event":"participant_joined","id":"EV_1","room":{"name":"ls_x"}}'
    for signature in ("", "   ", "deadbeef", "0" * 64):
        with pytest.raises(VideoProviderError) as excinfo:
            adapter.verify_event(signature, body)
        assert excinfo.value.code == "SIGNATURE_INVALID"
        assert not excinfo.value.retryable
    # ...and with no credential presented by ANY route at all.
    for headers in (None, {}, {"content-type": "application/webhook+json"}):
        with pytest.raises(VideoProviderError) as excinfo:
            adapter.verify_event(raw_body=body, headers=headers)
        assert excinfo.value.code == "SIGNATURE_INVALID"
        assert not excinfo.value.retryable


def test_livekit_reissue_in_the_same_second_mints_a_distinct_bearer(monkeypatch):
    """A superseding grant must not hand the caller the same raw JWT again."""
    import uuid
    from datetime import datetime, timezone

    adapter = LiveKitCommunityAdapter(
        "http://livekit.invalid:7880",
        "APIunitTestKeyValue",
        "0123456789abcdef0123456789abcdef",
    )
    probes = []
    monkeypatch.setattr(
        adapter,
        "_twirp",
        lambda method, payload: probes.append((method, payload)) or {"rooms": []},
    )
    session_id = uuid.uuid4()
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    first = adapter.issue_credential(
        session_id, "participant-opaque", "publish,subscribe", 300, now=now
    )
    second = adapter.issue_credential(
        session_id, "participant-opaque", "publish,subscribe", 300, now=now
    )
    assert first.raw_token != second.raw_token
    assert first.token_hash != second.token_hash
    assert first.room_ref == second.room_ref
    assert first.participant_ref == second.participant_ref
    assert first.permissions == second.permissions
    assert first.expires_at == second.expires_at
    assert probes == [
        ("ListRooms", {"names": [first.room_ref]}),
        ("ListRooms", {"names": [second.room_ref]}),
    ]


def test_livekit_refuses_to_mint_a_bearer_when_the_sfu_is_unreachable(monkeypatch):
    import httpx
    import uuid

    adapter = LiveKitCommunityAdapter(
        "http://livekit.invalid:7880",
        "APIunitTestKeyValue",
        "0123456789abcdef0123456789abcdef",
    )

    def offline(*_args, **_kwargs):
        raise httpx.ConnectError("provider is deliberately offline")

    monkeypatch.setattr(httpx, "post", offline)
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.issue_credential(
            uuid.uuid4(), "participant-opaque", "publish,subscribe", 300
        )
    assert excinfo.value.code == "PROVIDER_UNREACHABLE"
    assert excinfo.value.retryable is True


def test_signature_header_names_are_documented_where_operators_will_look():
    """BOTH transports must be documented, because the adapters really differ.

    Previously this asserted one hard-coded route-level header
    (``tutoring.VIDEO_SIGNATURE_HEADER``). The route no longer picks a header —
    each adapter declares its own — so the obligation is that the runbook names
    the header of every adapter an operator can select.
    """
    from app.services.providers.video_provider import (
        DeterministicVideoAdapter,
        LiveKitCommunityAdapter as _LK,
    )

    text = RUNBOOK.read_text(encoding="utf-8")
    for adapter in (DeterministicVideoAdapter, _LK):
        assert adapter.signature_header in text, (
            f"the runbook must name the header {adapter.name} verifies"
        )
    # The route must not have re-acquired a single hard-coded video header.
    from app.api.v1 import tutoring as ep

    assert not hasattr(ep, "VIDEO_SIGNATURE_HEADER"), (
        "the video signature header belongs to the adapter, not the route"
    )


# --------------------------------------------------------------------------- #
# adapter <-> server coupling that is easy to get wrong
# --------------------------------------------------------------------------- #


def test_rooms_are_auto_created_because_ensure_room_never_calls_the_provider():
    """``LiveKitCommunityAdapter.ensure_room`` derives a name and returns.

    Nothing ever calls CreateRoom, so a server configured with
    ``room.auto_create: false`` would fail every single join.
    """
    import inspect

    source = inspect.getsource(LiveKitCommunityAdapter.ensure_room)
    assert "_twirp" not in source and "httpx" not in source
    for mode in TEMPLATES:
        assert _render(mode)["livekit"]["room"]["auto_create"] is True, mode


def test_departure_timeout_outlives_a_reconnect():
    """``room_finished`` revokes EVERY grant for the session.

    With the upstream default of 20s, a brief blip that dropped both participants
    would revoke both credentials. Keep this comfortably above any client
    reconnect window, and never below the join-credential TTL.
    """
    ttl = Settings(_env_file=None).join_credential_ttl_seconds
    for mode in TEMPLATES:
        room = _render(mode)["livekit"]["room"]
        assert room["departure_timeout"] >= ttl, mode
        assert room["empty_timeout"] >= ttl, mode
        # Not 2: a reconnect race would look like a full room.
        assert room["max_participants"] > 2, mode


# --------------------------------------------------------------------------- #
# no committed secrets
# --------------------------------------------------------------------------- #


def test_no_secret_literal_is_committed_under_infra_video():
    """Name-based scan of real ASSIGNMENTS.

    Comment lines are skipped: every one of these files explains what its secrets
    are and where they come from, and a scanner that cannot tell prose from a
    value produces noise that gets silenced rather than fixed. Comments are still
    covered — by ``test_no_high_entropy_string_is_assigned_to_a_credential_name``
    below, which scans every line of every file including comments. A secret long
    enough to be a secret cannot hide in either pass.
    """
    offenders: list[str] = []
    for path in _committed_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.lstrip().startswith("#"):
                continue
            for name, value in _SECRETISH_ASSIGNMENT.findall(line):
                if value.startswith(("${", "$(", "<", "`${")):
                    continue  # a placeholder or a shell substitution
                cleaned = value.strip("`'\",;")
                if not cleaned or cleaned.isdigit():
                    continue
                if _is_placeholder_secret(cleaned):
                    continue
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {name}")
    assert not offenders, "possible committed secret(s): " + "; ".join(offenders)


def test_no_high_entropy_string_is_assigned_to_a_credential_name():
    pattern = re.compile(
        r"(?i)\b[a-z0-9_.\-]*(?:secret|password|token|credential)[a-z0-9_.\-]*"
        r"\s*[:=]\s*['\"]?([A-Za-z0-9+/=_-]{16,})"
    )
    for path in _committed_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = pattern.search(line)
            assert not match, (
                f"{path.relative_to(REPO)}:{lineno} assigns a high-entropy "
                "literal to a credential-shaped name"
            )


def test_rendered_output_is_gitignored():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "infra/video/rendered/" in ignore
    # The tracked template/env files must NOT be swept up by that rule.
    assert ENV_EXAMPLE.name == ".env.example"  # re-included by `!.env.example`


def test_nothing_is_rendered_into_the_tracked_tree_by_accident():
    stray = [
        p.name
        for p in INFRA.iterdir()
        if p.is_file() and p.name in {"livekit.yaml", "turnserver.conf"}
    ]
    assert not stray, f"rendered output committed next to its template: {stray}"


# --------------------------------------------------------------------------- #
# the renderer
# --------------------------------------------------------------------------- #


def _render(mode: str, **overrides: str) -> dict[str, dict]:
    """Render both service configs in memory and parse the LiveKit YAML."""
    module = _renderer()
    values = _base_env(**overrides)
    rendered = module.render(mode, values)
    livekit_body = rendered["livekit"][1]
    return {
        "livekit": yaml.safe_load(livekit_body),
        "livekit_text": livekit_body,
        "coturn_text": rendered["coturn"][1],
    }


def test_renderer_placeholder_set_covers_the_apps_fail_closed_set():
    """The renderer must refuse everything ``Settings`` refuses, and more.

    A superset, not equality: the renderer is allowed to be stricter (it also
    rejects "coturn", "turn", "password"), but it must never accept a value the
    application would then fail closed on — that combination produces infra that
    comes up healthy in front of a backend that refuses to boot.
    """
    assert _PLACEHOLDER_SECRETS <= _renderer().PLACEHOLDER_SECRETS


def test_renderer_produces_parseable_configs_for_both_modes():
    for mode in TEMPLATES:
        out = _render(mode)
        assert "${" not in out["livekit_text"], mode
        assert "${" not in out["coturn_text"], mode
        assert f"NYAYONE-VIDEO-MODE: {mode}" in out["livekit_text"]
        assert f"NYAYONE-VIDEO-MODE: {mode}" in out["coturn_text"]
        config = out["livekit"]
        assert config["port"] == 7880
        # INFO participant-init records contain SDP/ICE diagnostics. A normal
        # deployment must not place those media credentials in application
        # logs merely to obtain verbose provider traces.
        assert config["logging"]["level"] == "warn"
        assert config["rtc"]["udp_port"] == (1141 if mode == "direct" else 7882)
        # port_range_* must stay unset for udp_port to take effect upstream.
        assert "port_range_start" not in config["rtc"]
        assert "port_range_end" not in config["rtc"]
        assert len(config["rtc"]["turn_servers"]) == 2
        protocols = {s["protocol"] for s in config["rtc"]["turn_servers"]}
        assert protocols == {"udp", "tcp"}
        for server in config["rtc"]["turn_servers"]:
            assert server["host"] == _base_env()["TURN_PUBLIC_HOST"]
            assert server["port"] == int(_base_env()["TURN_PUBLIC_PORT"])
            assert server["ttl"] == 3600


def test_renderer_refuses_direct_mode_without_an_advertise_ip(monkeypatch):
    module = _renderer()
    for name, value in _base_env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LIVEKIT_ADVERTISE_IP", raising=False)
    # forced-turn is happy without it (it hard-codes the internal address)...
    assert module.resolve(None, "forced-turn")
    # ...direct is not: an unreachable advertised address fails at ICE time with
    # no useful error, so it is refused at render time instead.
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "direct")
    assert "LIVEKIT_ADVERTISE_IP" in str(excinfo.value)


def test_renderer_refuses_the_committed_env_example():
    """The shipped template must be un-deployable as-is."""
    module = _renderer()
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(ENV_EXAMPLE, "forced-turn")
    message = str(excinfo.value)
    assert "LIVEKIT_API_SECRET" in message
    assert "TURN_STATIC_AUTH_SECRET" in message
    # And the refusal must not quote the offending value back at the operator.
    assert "changeme" not in message


def test_renderer_refuses_an_empty_environment(monkeypatch):
    module = _renderer()
    for name in module.COMMON_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "forced-turn")
    message = str(excinfo.value)
    for name in module.COMMON_VARS:
        assert name in message, f"{name} not named in the refusal"


def test_renderer_url_and_key_rules(monkeypatch):
    module = _renderer()
    for name, value in _base_env().items():
        monkeypatch.setenv(name, value)

    monkeypatch.setenv("VIDEO_WEBHOOK_URL", "http://backend:1031/api/v1/wrong")
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "forced-turn")
    assert module.WEBHOOK_PATH in str(excinfo.value)

    monkeypatch.setenv("VIDEO_WEBHOOK_URL", _base_env()["VIDEO_WEBHOOK_URL"])
    monkeypatch.setenv("LIVEKIT_API_KEY", "bad: key")
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "forced-turn")
    assert "LIVEKIT_API_KEY" in str(excinfo.value)

    monkeypatch.setenv("LIVEKIT_API_KEY", "APIokKey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "tooshort")
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "forced-turn")
    assert "16" in str(excinfo.value)

    monkeypatch.setenv("LIVEKIT_API_SECRET", _base_env()["LIVEKIT_API_SECRET"])
    monkeypatch.setenv("TURN_PUBLIC_PORT", "70000")
    with pytest.raises(module.RenderError) as excinfo:
        module.resolve(None, "forced-turn")
    assert "TURN_PUBLIC_PORT" in str(excinfo.value)


def test_renderer_writes_the_secret_file_private_and_the_other_readable(tmp_path):
    module = _renderer()
    written = module.write(tmp_path / "out", module.render("forced-turn", _base_env()))
    modes = {p.name: p.stat().st_mode & 0o777 for p in written}
    # Holds LIVEKIT_API_SECRET; the livekit image runs as root and can read 0600.
    assert modes["livekit.yaml"] == 0o600
    # Holds no secret; coturn runs as `nobody` and could not read 0600.
    assert modes["turnserver.conf"] == 0o644
    assert (tmp_path / "out").stat().st_mode & 0o777 == 0o700
    body = (tmp_path / "out" / "livekit.yaml").read_text(encoding="utf-8")
    assert "GENERATED by scripts/render_video_infra_config.py" in body


def test_renderer_cli_check_mode_writes_nothing(tmp_path, monkeypatch):
    module = _renderer()
    for name, value in _base_env().items():
        monkeypatch.setenv(name, value)
    out = tmp_path / "nope"
    assert module.main(["--check", "--out-dir", str(out)]) == 0
    assert not out.exists()
    assert module.main(["--out-dir", str(out)]) == 0
    assert (out / "livekit.yaml").is_file()


def test_renderer_reports_a_missing_placeholder_instead_of_writing_it(tmp_path):
    module = _renderer()
    template = tmp_path / "livekit.mystery.yaml.tmpl"
    template.write_text("port: 7880\nmystery: ${NOT_DECLARED}\n", encoding="utf-8")
    with pytest.raises(module.RenderError) as excinfo:
        module.render_one(template, _base_env(), "mystery")
    assert "NOT_DECLARED" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# documentation obligations that are cheap to enforce and expensive to forget
# --------------------------------------------------------------------------- #


def test_runbook_covers_every_required_operation():
    text = RUNBOOK.read_text(encoding="utf-8")
    for heading in (
        "Bring-up",
        "Health and readiness",
        "Forced-TURN",
        "Credential rotation",
        "When the provider is unreachable",
        "Restart and reconnect",
        "Rollback",
        "Environment-blocked checks",
    ):
        assert heading in text, f"RUNBOOK does not cover: {heading}"


def test_runbook_marks_runtime_checks_as_unexecuted_not_passing():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "UNEXECUTED" in text
    assert "ENVIRONMENT-BLOCKED" in text
    # The forced-TURN smoke test in particular must never read as green.
    section = text.split("FORCED-TURN smoke test")[1]
    assert "UNEXECUTED" in section.split("\n")[0]
