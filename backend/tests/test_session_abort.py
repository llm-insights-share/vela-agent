"""Session cooperative abort registry tests."""
from services.session_abort import clear_abort, is_aborted, request_abort


def test_abort_flag_is_session_scoped():
    clear_abort("a")
    clear_abort("b")
    request_abort("a")
    assert is_aborted("a") is True
    assert is_aborted("b") is False
    clear_abort("a")
    assert is_aborted("a") is False


def test_request_abort_idempotent():
    clear_abort("x")
    request_abort("x")
    request_abort("x")
    assert is_aborted("x") is True
    clear_abort("x")
