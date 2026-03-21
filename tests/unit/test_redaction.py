"""Unit tests for the redaction pipeline."""


from arcane.infra.redaction import load_memoryignore, redact


class TestRedact:
    def test_explicit_redacted_tags(self):
        text = "The key is <redacted>sk_live_abc123</redacted> ok?"
        result = redact(text)
        assert "sk_live_abc123" not in result
        assert "[REDACTED]" in result

    def test_auto_pattern_stripe_key(self):
        result = redact("My key: sk_live_abc123xyz")
        assert "sk_live_abc123xyz" not in result
        assert "[REDACTED]" in result

    def test_auto_pattern_github_token(self):
        result = redact("Token: ghp_abcdef1234567890")
        assert "ghp_abcdef1234567890" not in result

    def test_auto_pattern_aws_key(self):
        result = redact("Key: AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_auto_pattern_slack_token(self):
        result = redact("Token: xoxb-123-456-abc")
        assert "xoxb-123-456-abc" not in result

    def test_auto_pattern_password(self):
        result = redact("password = 'super_secret'")
        assert "super_secret" not in result

    def test_auto_pattern_api_key(self):
        result = redact("api_key = 'my-key-123'")
        assert "my-key-123" not in result

    def test_jwt_pattern(self):
        jwt = "eyJhbGciOiJIUzI.eyJzdWIiOiIxMjM0NTY3ODkw"
        result = redact(f"Bearer {jwt}")
        assert jwt not in result

    def test_private_key_header(self):
        result = redact("-----BEGIN RSA PRIVATE KEY----- ...")
        assert "PRIVATE KEY" not in result

    def test_clean_text_unchanged(self):
        text = "This is a normal log message about deployment."
        assert redact(text) == text

    def test_extra_patterns(self):
        result = redact("internal-secret-value", extra_patterns=[r"internal-secret-\w+"])
        assert "internal-secret-value" not in result

    def test_nested_redacted_tags(self):
        text = "<redacted>outer <redacted>inner</redacted> more</redacted>"
        result = redact(text)
        assert "<redacted>" not in result
        assert "</redacted>" not in result


class TestLoadMemoryignore:
    def test_load_existing_file(self, tmp_path):
        ignore_file = tmp_path / ".memoryignore"
        ignore_file.write_text("pattern1\n# comment\npattern2\n\n")
        patterns = load_memoryignore(str(ignore_file))
        assert patterns == ["pattern1", "pattern2"]

    def test_missing_file_returns_empty(self):
        patterns = load_memoryignore("/nonexistent/.memoryignore")
        assert patterns == []
