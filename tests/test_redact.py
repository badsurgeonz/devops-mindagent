from app.redact import redact


def test_redact_jwt():
    text = "Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
    out = redact(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out


def test_redact_phone_and_email():
    out = redact("联系 13812345678 或 a@b.com")
    assert "13812345678" not in out
    assert "a@b.com" not in out


def test_redact_secret_key():
    out = redact("api_key=sk-abc123456")
    assert "sk-abc123456" not in out