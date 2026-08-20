from services.mcp.crypto import decrypt_secret, encrypt_secret
from services.mcp.oauth import build_authorization_url, generate_pkce, parse_www_authenticate


def test_encrypt_roundtrip():
    token = "access-token-xyz"
    cipher = encrypt_secret(token)
    assert cipher != token
    assert decrypt_secret(cipher) == token
    assert decrypt_secret("") == ""
    assert decrypt_secret("not-a-token") == ""


def test_build_authorization_url_includes_pkce():
    _, challenge = generate_pkce()
    url = build_authorization_url(
        {"authorization_endpoint": "https://auth.example.com/authorize"},
        client_id="cid",
        redirect_uri="http://localhost:8000/api/v1/mcp/oauth/callback",
        state="st",
        code_challenge=challenge,
        resource="https://mcp.example.com",
        scope="openid",
    )
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "client_id=cid" in url
    assert "resource=" in url


def test_www_authenticate_bearer_params():
    parsed = parse_www_authenticate(
        'Bearer error="invalid_token", resource_metadata="https://ex/.well-known/oauth-protected-resource"'
    )
    assert parsed["error"] == "invalid_token"
    assert parsed["resource_metadata"].startswith("https://ex/")
