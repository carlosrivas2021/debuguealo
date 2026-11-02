from copy import deepcopy

import pytest

from debugpilot.docker.compose_overrides import (
    apply_service_overrides,
    validate_service_overrides,
)


def test_environment_overrides_merge_and_preserve_canonical_values():
    model = {"services": {"api": {"environment": {"KEEP": "yes", "MODE": "old"}}}}
    original = deepcopy(model)
    overrides = {"services": {"api": {"environment": {"MODE": "dev"}}}}
    validated = validate_service_overrides(overrides)

    result = apply_service_overrides(model, validated)

    assert result["services"]["api"]["environment"] == {"KEEP": "yes", "MODE": "dev"}
    assert model == original
    assert overrides == {"services": {"api": {"environment": {"MODE": "dev"}}}}


def test_ports_replace_and_empty_ports_clear_all():
    model = {"services": {"api": {"ports": ["80:80", "443:443"]}}}
    replacement = validate_service_overrides(
        {"services": {"api": {"ports": ["9000:80"]}}}
    )
    cleared = validate_service_overrides({"services": {"api": {"ports": []}}})

    assert apply_service_overrides(model, replacement)["services"]["api"]["ports"] == [
        "9000:80"
    ]
    assert apply_service_overrides(model, cleared)["services"]["api"]["ports"] == []
    assert model["services"]["api"]["ports"] == ["80:80", "443:443"]


def test_unrelated_model_data_is_preserved_and_detached():
    model = {
        "name": "demo",
        "services": {
            "api": {"image": "example/api", "environment": {"KEEP": None}},
            "worker": {"image": "example/worker"},
        },
        "networks": {"default": {"driver": "bridge"}},
    }
    original = deepcopy(model)
    result = apply_service_overrides(
        model, validate_service_overrides({"services": {"api": {"environment": {"NEW": "v"}}}})
    )

    assert result["services"]["api"] == {
        "image": "example/api",
        "environment": {"KEEP": None, "NEW": "v"},
    }
    assert result["services"]["worker"] == original["services"]["worker"]
    assert result["networks"] == original["networks"]
    assert model == original
    result["networks"]["default"]["driver"] = "changed"
    assert model == original


@pytest.mark.parametrize(
    "payload",
    [
        {"services": {"api": {"command": "ignored"}}},
        {"services": {"bad/name": {"ports": []}}},
        {"services": {"api": {"environment": {"MODE": None}}}},
        {"services": {"api": {"ports": [80]}}},
        {"unknown": {}},
    ],
)
def test_malformed_or_unsupported_override_is_rejected_without_leak(payload):
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        validate_service_overrides(payload)
    assert payload == before


def test_unknown_target_is_rejected_without_mutating_model_or_override():
    model = {"services": {"api": {"environment": {}}}}
    original = deepcopy(model)
    overrides = {"services": {"missing": {"ports": []}}}
    before = deepcopy(overrides)
    validated = validate_service_overrides(overrides)

    with pytest.raises(ValueError):
        apply_service_overrides(model, validated)
    assert model == original
    assert overrides == before


def test_validated_override_is_immutable_detached_literal_and_redacted():
    overrides = {
        "services": {
            "api": {
                "environment": {"TOKEN": "literal-$VALUE"},
                "ports": ["9000:80"],
            }
        }
    }
    validated = validate_service_overrides(overrides)
    overrides["services"]["api"]["environment"]["TOKEN"] = "mutated"
    overrides["services"]["api"]["ports"].append("9001:81")

    applied = apply_service_overrides({"services": {"api": {}}}, validated)

    assert applied["services"]["api"]["environment"] == {"TOKEN": "literal-$VALUE"}
    assert applied["services"]["api"]["ports"] == ["9000:80"]
    assert "literal-$VALUE" not in repr(validated)
    assert "literal-$VALUE" not in str(validated)


def test_absent_and_empty_overrides_are_detached_noops():
    model = {"services": {"api": {"environment": {"KEEP": None}}}}
    original = deepcopy(model)
    for payload in (None, {}, {"services": {}}):
        result = apply_service_overrides(model, validate_service_overrides(payload))
        assert result == original
        assert result is not model
        result["services"]["api"]["environment"]["KEEP"] = "changed"
        assert model == original


def test_invalid_environment_text_and_port_text_are_rejected_without_leak():
    payloads = (
        {"services": {"api": {"environment": {"": "secret"}}}},
        {"services": {"api": {"environment": {"A=B": "secret"}}}},
        {"services": {"api": {"environment": {"TOKEN": "secret\x00"}}}},
        {"services": {"api": {"environment": {"TOKEN": "secret\ud800"}}}},
        {"services": {"api": {"ports": ["9000:80\x00"]}}},
        {"services": {"api": {"ports": ["9000:80\ud800"]}}},
    )
    for payload in payloads:
        original = deepcopy(payload)
        with pytest.raises(ValueError) as error:
            validate_service_overrides(payload)
        assert "secret" not in str(error.value)
        assert payload == original


def test_secret_does_not_appear_in_validation_error():
    payload = {"services": {"api": {"environment": {"TOKEN": "fake-secret"}, "extra": "x"}}}
    original = deepcopy(payload)

    with pytest.raises(ValueError) as error:
        validate_service_overrides(payload)

    assert "fake-secret" not in str(error.value)
    assert payload == original


def test_render_appends_literal_environment_and_replacing_ports():
    from debugpilot.docker.compose_overrides import render_service_overrides

    rendered = render_service_overrides(
        validate_service_overrides(
            {
                "services": {
                    "api": {
                        "environment": {"A": 'x$Y "q" \\ é 😀', "EMPTY": ""},
                        "ports": ["127.0.0.1:9000:80"],
                    },
                    "worker": {"ports": []},
                    "noop": {},
                }
            }
        )
    )

    assert rendered == (
        "services:\n"
        '  "api":\n'
        "    environment:\n"
        '      "A": "x$$Y \\"q\\" \\\\ \\u00e9 \\U0001f600"\n'
        '      "EMPTY": ""\n'
        "    ports: !override\n"
        '      - "127.0.0.1:9000:80"\n'
        '  "worker":\n'
        "    ports: !override []\n"
        '  "noop": {}\n'
    )


def test_render_requires_validated_overrides():
    from debugpilot.docker.compose_overrides import render_service_overrides

    with pytest.raises(ValueError):
        render_service_overrides({"services": {}})
