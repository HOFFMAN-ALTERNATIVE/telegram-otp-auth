from collections import Counter

from otp_auth.codes import codes_match, digest_code, generate_code

S = b"k" * 32


def test_code_format() -> None:
    for n in (6, 8):
        c = generate_code(n)
        assert len(c) == n
        assert c.isdigit()


def test_codes_are_uniformish() -> None:
    digits = Counter("".join(generate_code(6) for _ in range(3000)))
    assert set(digits) == set("0123456789")
    assert max(digits.values()) / min(digits.values()) < 1.3


def test_digest_is_bound_to_challenge_and_secret() -> None:
    d = digest_code(S, "ch1", "123456")
    assert d != digest_code(S, "ch2", "123456")
    assert d != digest_code(b"z" * 32, "ch1", "123456")
    assert "123456" not in d
    assert codes_match(d, S, "ch1", "123456")
    assert not codes_match(d, S, "ch1", "123457")
