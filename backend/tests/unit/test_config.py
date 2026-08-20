"""Config: loopback enforcement, path resolution, and key masking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gaugix.config import (
    Settings,
    mask_key,
    provider_key_status,
    read_api_key,
    redact_for_display,
    reset_settings_cache,
)


def test_host_defaults_to_loopback():
    assert Settings().host == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_non_loopback_host_is_rejected(host):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(host=host)


def test_relative_data_dir_resolves_against_repo_root():
    settings = Settings(data_dir=Path("./data"))
    assert settings.resolved_data_dir.is_absolute()
    assert settings.resolved_data_dir.name == "data"


def test_db_path_defaults_inside_data_dir(tmp_path):
    settings = Settings(data_dir=tmp_path, db_path=None)
    assert settings.resolved_db_path == tmp_path / "gaugix.db"
    assert settings.database_url.startswith("sqlite:///")


def test_ensure_dirs_creates_the_tree(tmp_path):
    settings = Settings(data_dir=tmp_path / "fresh")
    settings.ensure_dirs()
    assert settings.artifacts_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.exports_dir.is_dir()


def test_mask_key_never_leaks_the_secret():
    secret = "test-key-not-a-real-secret-1234"
    masked = mask_key(secret)
    assert masked == "…1234"
    assert secret not in masked


def test_mask_key_on_short_values_reveals_nothing():
    assert mask_key("abc") == "…"


def test_provider_key_status_reports_absent_keys(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    status = provider_key_status()
    assert set(status) == {"anthropic", "openai", "gemini", "openrouter"}
    assert all(not s["present"] for s in status.values())
    assert all(s["masked"] is None for s in status.values())


def test_provider_key_status_masks_present_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secretvalue9876")
    status = provider_key_status()
    assert status["openai"]["present"] is True
    assert status["openai"]["masked"] == "…9876"
    assert "secretvalue" not in str(status)


def test_read_api_key_returns_none_for_missing_or_blank(monkeypatch):
    monkeypatch.setenv("BLANK_KEY", "   ")
    assert read_api_key(None) is None
    assert read_api_key("NOT_SET_ANYWHERE") is None
    assert read_api_key("BLANK_KEY") is None


def test_read_api_key_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "  value  ")
    assert read_api_key("SOME_KEY") == "value"


def test_frozen_credentials_snapshot_lazily_and_status_uses_the_same_view(monkeypatch):
    monkeypatch.setenv("GAUGIX_FREEZE_CREDENTIALS", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "first-credential-1234")
    reset_settings_cache()
    try:
        assert read_api_key("OPENAI_API_KEY") == "first-credential-1234"
        monkeypatch.setenv("OPENAI_API_KEY", "later-credential-9999")

        assert read_api_key("OPENAI_API_KEY") == "first-credential-1234"
        status = provider_key_status()
        assert status["openai"]["present"] is True
        assert status["openai"]["masked"] == "…1234"
    finally:
        reset_settings_cache()


def test_redact_for_display_keeps_env_names_but_removes_literal_credentials():
    secret = "sk-test-secret-value-123456"
    value = {
        "api_key_env": "OPENROUTER_API_KEY",
        "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"},
        "params": {
            "extra_headers": {
                "Authorization": f"Bearer {secret}",
                "X-MT-VK": "literal-vk-value",
            },
            "nested": {"access_token": secret},
        },
    }

    redacted = redact_for_display(value)

    assert redacted["api_key_env"] == "OPENROUTER_API_KEY"
    assert redacted["request_headers_from_env"] == {"x-mt-vk": "MT0_EVAL_VK"}
    assert redacted["params"]["extra_headers"] == {
        "Authorization": "[REDACTED]",
        "X-MT-VK": "[REDACTED]",
    }
    assert redacted["params"]["nested"]["access_token"] == "[REDACTED]"
    assert secret not in str(redacted)


def test_redact_for_display_sanitizes_structured_provider_text():
    secret = "sk-provider-debug-secret-123456"
    raw = json.dumps(
        {
            "error": {
                "authorization": f"Bearer {secret}",
                "message": f"invalid credential: {secret}",
            }
        }
    )

    result = redact_for_display(raw)

    assert secret not in result
    assert "[REDACTED]" in result


def test_redact_for_display_sanitizes_json_embedded_in_an_error_message():
    raw = 'provider failed: {"api_key":"opaque-provider-credential"}'

    result = redact_for_display(raw)

    assert "opaque-provider-credential" not in result
    assert result == 'provider failed: {"api_key":"[REDACTED]"}'


def test_redact_for_display_sanitizes_unquoted_error_fields():
    raw = "api_key=opaque-api-value x-mt-vk: opaque-vk-value authorization: Bearer opaque"

    result = redact_for_display(raw)

    assert "opaque-api-value" not in result
    assert "opaque-vk-value" not in result
    assert "Bearer opaque" not in result
    assert result.count("[REDACTED]") == 3


def test_redact_for_display_handles_an_unterminated_quoted_backslash_run_linearly():
    raw = 'password: "' + ("\\" * 10_000)

    result = redact_for_display(raw)

    assert result == 'password: "[REDACTED]'


def test_redact_for_display_handles_pathologically_deep_json_text():
    raw = "[" * 5_000

    assert redact_for_display(raw) == raw


def test_redact_for_display_handles_json_integer_digit_limits():
    raw = "[" + ("9" * 5_000) + "]"

    assert redact_for_display(raw) == raw


def test_redact_for_display_masks_credentials_folded_after_a_scheme():
    for raw in (
        "authorization: Bearer\nx-opaque-credential",
        'authorization: "Bearer\nx-opaque-credential"',
    ):
        result = redact_for_display(raw)
        assert "x-opaque-credential" not in result
        assert "[REDACTED]" in result


def test_redact_for_display_preserves_adjacent_field_boundaries():
    cases = (
        "authorization: Bearer\nx-api-key: opaquesecret",
        'authorization: "Bearer abc" x-api-key: "opaquesecret"',
    )

    for raw in cases:
        result = redact_for_display(raw)
        assert "opaquesecret" not in result
        assert result.count("[REDACTED]") == 2


def test_redact_for_display_preserves_parent_semantics_for_json_strings():
    result = redact_for_display({"extra_headers": '{"X-Custom-Auth": "hunter2-opaque"}'})

    assert "hunter2-opaque" not in str(result)
    assert "[REDACTED]" in str(result)


def test_redact_for_display_masks_a_quoted_token_after_an_unquoted_scheme():
    result = redact_for_display('authorization: Bearer "opaque-token-value"')

    assert "opaque-token-value" not in result
    assert result == "authorization: [REDACTED]"


def test_redact_for_display_does_not_swallow_a_field_after_an_empty_secret():
    for raw in ("secret:\npassword: hunter2", "token: password: hunter2"):
        result = redact_for_display(raw)
        assert "hunter2" not in result
        assert result.count("[REDACTED]") == 2


def test_redact_for_display_treats_plain_header_strings_as_sensitive():
    for value in (
        {"extra_headers": ["X-Custom-Auth: hunter2"]},
        {"headers": "X-Custom-Auth: hunter2"},
    ):
        result = redact_for_display(value)
        assert "hunter2" not in str(result)
        assert "[REDACTED]" in str(result)


def test_redact_for_display_recognizes_compound_structured_secret_keys():
    value = {
        "client_secret": "client-value",
        "session_token": "session-value",
        "x_goog_api_key": "google-value",
        "monkey": "ordinary-value",
    }

    result = redact_for_display(value)

    assert result["client_secret"] == "[REDACTED]"
    assert result["session_token"] == "[REDACTED]"
    assert result["x_goog_api_key"] == "[REDACTED]"
    assert result["monkey"] == "ordinary-value"


def test_redact_for_display_sanitizes_secrets_in_mapping_keys():
    token = "sk-proj-abc123def456"
    result = redact_for_display(
        {
            "api_keys": {token: {"quota": 1}},
            "extra_headers": {"Authorization: Bearer opaque-secret": ""},
        }
    )

    rendered = str(result)
    assert token not in rendered
    assert "opaque-secret" not in rendered
    assert "[REDACTED]" in rendered
    assert token not in redact_for_display(json.dumps({token: 1}))


def test_redact_for_display_recognizes_private_keys_and_plural_credentials():
    result = redact_for_display(
        {
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEv...",
            "nested_credentials": "opaque-user-pass",
        }
    )

    assert "MIIEv" not in str(result)
    assert "opaque-user-pass" not in str(result)
    assert "opaque-user-pass" not in redact_for_display("credentials: opaque-user-pass")


def test_redact_for_display_recognizes_camel_case_secret_keys():
    value = {
        "accessToken": "opaque-access-token",
        "clientSecret": "opaque-client-secret",
        "privateKey": "-----BEGIN PRIVATE KEY-----\nMIIEv...",
        "apiKeyEnv": "OPENROUTER_API_KEY",
    }

    result = redact_for_display(value)

    assert result["accessToken"] == "[REDACTED]"
    assert result["clientSecret"] == "[REDACTED]"
    assert result["privateKey"] == "[REDACTED]"
    assert result["apiKeyEnv"] == "OPENROUTER_API_KEY"
    assert "opaque-access-token" not in redact_for_display(json.dumps(value))


def test_redact_for_display_caps_recursive_structures():
    value: object = "leaf"
    for _ in range(100):
        value = {"nested": value}

    assert "[REDACTED]" in str(redact_for_display(value))


@pytest.mark.parametrize(
    "token",
    (
        "ghp_0123456789abcdefghij",
        "gho_0123456789abcdefghij",
        "ghu_0123456789abcdefghij",
        "ghs_0123456789abcdefghij",
        "ghr_0123456789abcdefghij",
        "github_pat_0123456789abcdefghij",
    ),
)
def test_redact_for_display_masks_bare_github_tokens(token):
    result = redact_for_display(f"provider rejected credential {token}")

    assert token not in result
    assert "[REDACTED]" in result


@pytest.mark.parametrize("scheme", ("Token", "token", "Digest", "AWS4-HMAC-SHA256"))
def test_redact_for_display_masks_complete_authorization_values(scheme):
    secret = "opaque-authorization-credential"
    result = redact_for_display(f"authorization: {scheme} {secret}")

    assert secret not in result
    assert result == "authorization: [REDACTED]"


def test_redact_for_display_masks_compound_authorization_field_values():
    result = redact_for_display("upstream_authorization_header: Token opaque credential")

    assert "opaque credential" not in result
    assert result.endswith("[REDACTED]")


def test_redact_for_display_masks_structured_compound_authorization_fields():
    result = redact_for_display(
        {
            "authorization_header": "Bearer opaque-secret",
            "upstreamAuthorizationHeader": "Token opaque credential",
        }
    )

    assert result == {
        "authorization_header": "[REDACTED]",
        "upstreamAuthorizationHeader": "[REDACTED]",
    }


@pytest.mark.parametrize(
    "field",
    ("sessionToken", "clientSecret", "idToken", "proxyAuthorization"),
)
def test_redact_for_display_masks_camel_case_fields_in_free_text(field):
    result = redact_for_display(f'provider failed: {{"{field}": "opaque-camel-value"}}')

    assert "opaque-camel-value" not in result
    assert "[REDACTED]" in result


@pytest.mark.parametrize("container", ("default_headers", "request_headers"))
def test_redact_for_display_treats_sdk_header_containers_as_sensitive(container):
    result = redact_for_display({"params": {container: {"X-Custom-Auth": "literal-secret"}}})

    assert "literal-secret" not in str(result)
    assert result["params"][container]["X-Custom-Auth"] == "[REDACTED]"


def test_redact_for_display_masks_invalid_header_names_that_contain_secrets():
    result = redact_for_display(
        {"extra_headers": {"X-Custom-Auth: hunter2": "", "X-Normal": "secret-value"}}
    )

    assert "hunter2" not in str(result)
    assert "secret-value" not in str(result)
    assert "[REDACTED]" in str(result)


def test_redact_for_display_handles_many_colliding_sanitized_keys():
    value = {f"authorization: secret-{index}": index for index in range(2_000)}

    result = redact_for_display(value)

    assert len(result) == len(value)
    assert len(set(result)) == len(value)
    assert all("secret-" not in key for key in result)


def test_redact_for_display_recognizes_secret_words_inside_compound_keys():
    value = {
        "aws_secret_access_key": "opaque-aws-secret",
        "secretAccessKey": "opaque-camel-secret",
        "webhook_signing_key": "opaque-signing-key",
    }

    result = redact_for_display(value)

    assert result == dict.fromkeys(value, "[REDACTED]")
    assert "opaque-" not in redact_for_display("aws_secret_access_key=opaque-free-text-secret")


@pytest.mark.parametrize(
    "value",
    (
        'Digest username="user;admin", realm="private", response="password-derived-digest"',
        "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE, "
        "SignedHeaders=host;x-amz-date, Signature=opaque-hmac",
    ),
)
def test_redact_for_display_masks_comma_separated_authorization_parameters(value):
    result = redact_for_display(f"authorization: {value}")

    assert "username" not in result
    assert "password-derived-digest" not in result
    assert "opaque-hmac" not in result
    assert result == "authorization: [REDACTED]"


def test_redact_for_display_only_exposes_env_names_in_header_env_mappings():
    result = redact_for_display(
        {
            "request_headers_from_env": {
                "Authorization": "Bearer literal-secret",
                "X-MT-VK": "MT0_EVAL_VK",
            }
        }
    )

    assert result["request_headers_from_env"] == {
        "Authorization": "[REDACTED]",
        "X-MT-VK": "MT0_EVAL_VK",
    }
    assert "literal-secret" not in str(result)


def test_redact_for_display_handles_long_non_secret_identifier_text_linearly():
    raw = "a" * 100_000

    assert redact_for_display(raw) == raw


@pytest.mark.parametrize(
    "field",
    ("session_token", "id_token", "openai_api_key", "x_goog_api_key"),
)
def test_redact_for_display_masks_compound_token_and_api_key_fields_in_text(field):
    result = redact_for_display(f"{field}=opaque-compound-secret")

    assert "opaque-compound-secret" not in result
    assert result.endswith("[REDACTED]")


def test_redact_for_display_masks_indented_values_on_the_following_line():
    result = redact_for_display("api_key:\n  opaque-folded-secret")

    assert "opaque-folded-secret" not in result
    assert result == "api_key:\n  [REDACTED]"


def test_redact_for_display_masks_spaces_in_an_indented_folded_value():
    result = redact_for_display("password:\n  correct horse battery staple")

    assert "correct" not in result
    assert "horse battery staple" not in result
    assert result == "password:\n  [REDACTED]"


@pytest.mark.parametrize("raw", ("api_key:\n  ", "password:\r\t"))
def test_redact_for_display_handles_folded_indentation_at_end_of_input(raw):
    result = redact_for_display(raw)

    assert result.endswith("[REDACTED]")


def test_redact_for_display_masks_yaml_private_key_block_scalars():
    raw = (
        "private_key: |\n"
        "  -----BEGIN PRIVATE KEY-----\n"
        "  MIIEv-opaque-key-material\n"
        "ordinary: visible"
    )

    result = redact_for_display(raw)

    assert "MIIEv-opaque-key-material" not in result
    assert "ordinary: visible" in result
    assert result.startswith("private_key: [REDACTED]")


def test_redact_for_display_masks_obs_folded_secret_values():
    result = redact_for_display("x-api-key: AAAA\r\n BBBB\r\nordinary: visible")

    assert "AAAA" not in result
    assert "BBBB" not in result
    assert "ordinary: visible" in result


def test_redact_for_display_masks_obs_fold_after_a_quoted_secret_value():
    result = redact_for_display('x-api-key: "AAAA"\r\n BBBB\r\nordinary: visible')

    assert "AAAA" not in result
    assert "BBBB" not in result
    assert "ordinary: visible" in result


def test_redact_for_display_masks_folded_sigv4_authorization():
    raw = (
        "authorization: AWS4-HMAC-SHA256\n"
        "  Credential=AKIAEXAMPLE, SignedHeaders=host, Signature=opaque-hmac"
    )

    result = redact_for_display(raw)

    assert "AKIAEXAMPLE" not in result
    assert "opaque-hmac" not in result
    assert result == "authorization: [REDACTED]"


def test_redact_for_display_preserves_unindented_lines_after_authorization():
    raw = "authorization: Bearer opaque\nstatus: 429\nprovider detail"

    result = redact_for_display(raw)

    assert "opaque" not in result
    assert "status: 429\nprovider detail" in result


@pytest.mark.parametrize(
    "raw",
    (
        "credentials: |\n  line1\n\n  line2\nordinary: visible",
        "api_key:\n\n  opaque-folded-value\nordinary: visible",
    ),
)
def test_redact_for_display_masks_indented_values_across_blank_lines(raw):
    result = redact_for_display(raw)

    assert "line1" not in result
    assert "line2" not in result
    assert "opaque-folded-value" not in result
    assert "ordinary: visible" in result


def test_redact_for_display_masks_plural_secret_containers():
    result = redact_for_display(
        {
            "api_keys": {"tenant": "opaque-api-key"},
            "tokens": ["opaque-token"],
            "total_tokens": 42,
        }
    )

    assert result["api_keys"] == "[REDACTED]"
    assert result["tokens"] == "[REDACTED]"
    assert result["total_tokens"] == 42
    assert "opaque-" not in str(result)


@pytest.mark.parametrize(
    "field",
    ("secrets", "passwords", "api_keys", "private_keys", "access_tokens", "signing_keys"),
)
def test_redact_for_display_masks_plural_secret_fields_in_text(field):
    result = redact_for_display(f"{field}: opaque-plural-secret")

    assert "opaque-plural-secret" not in result
    assert result.endswith("[REDACTED]")


def test_redact_for_display_preserves_plain_token_metric_text():
    assert redact_for_display("tokens: 42") == "tokens: 42"


def test_redact_for_display_masks_byte_values():
    result = redact_for_display(
        {"extra_headers": [b"Authorization: Bearer opaque-bytes"], "payload": b"opaque"}
    )

    assert "opaque" not in str(result)
    assert result["extra_headers"] == ["[REDACTED]"]
    assert result["payload"] == "[REDACTED]"


def test_redact_for_display_validates_env_reference_fields():
    result = redact_for_display(
        {"api_key_env": "literal secret phrase", "token_env_name": "VALID_TOKEN_ENV"}
    )

    assert result == {
        "api_key_env": "[REDACTED]",
        "token_env_name": "VALID_TOKEN_ENV",
    }
