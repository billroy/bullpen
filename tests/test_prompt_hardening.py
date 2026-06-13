"""Tests for provider-specific prompt/runtime hardening."""

from server.prompt_hardening import (
    TRUST_MODE_TRUSTED,
    TRUST_MODE_UNTRUSTED,
    harden_agent_argv,
)


def test_harden_opencode_trusted_adds_skip_permissions():
    argv = ["opencode", "run", "--format", "json"]

    hardened = harden_agent_argv("opencode", argv, trust_mode=TRUST_MODE_TRUSTED)

    assert "--dangerously-skip-permissions" in hardened
    assert argv == ["opencode", "run", "--format", "json"]


def test_harden_opencode_untrusted_does_not_add_skip_permissions():
    argv = ["opencode", "run", "--format", "json"]

    hardened = harden_agent_argv("opencode", argv, trust_mode=TRUST_MODE_UNTRUSTED)

    assert "--dangerously-skip-permissions" not in hardened


def test_harden_opencode_chat_does_not_add_skip_permissions():
    argv = ["opencode", "run", "--format", "json"]

    hardened = harden_agent_argv("opencode", argv, trust_mode=TRUST_MODE_TRUSTED, chat=True)

    assert "--dangerously-skip-permissions" not in hardened


def test_harden_claude_untrusted_still_gets_strict_mcp_config():
    argv = ["claude", "--print"]

    hardened = harden_agent_argv("claude", argv, trust_mode=TRUST_MODE_UNTRUSTED)

    assert "--strict-mcp-config" in hardened
    assert "--disallowedTools" in hardened
