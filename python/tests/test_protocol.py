import pytest
from d8tx.protocol import fmt_sticks, parse_line


def test_fmt_clamp_and_arm():
    line, ch = fmt_sticks([0, 1500, 3000, 1500, 1500, 1500, 2000, 1500])
    assert line == "S 1000 1500 2000 1500 1500 1500 1000 1500\n"
    line, ch = fmt_sticks([1000] * 6 + [2000, 1000], allow_arm=True)
    assert ch[6] == 2000


def test_fmt_bad_len():
    with pytest.raises(ValueError):
        fmt_sticks([1500] * 7)


def test_parse():
    assert parse_line("OK") == ("ok", {})
    assert parse_line("OK proto=1 fw=abc\r") == ("ok", {"proto": 1, "fw": "abc"})
    assert parse_line("ERR busy link active") == ("err", ("busy", "link active"))
    assert parse_line("EV link slots=3 late_max_us=9") == ("ev", ("link", {"slots": 3, "late_max_us": 9}))
    assert parse_line("hello")[0] == "other"


def test_max_line_enforced():
    import pytest
    from d8tx.protocol import MAX_LINE, check_line
    assert MAX_LINE == 95
    check_line("x" * 95)
    with pytest.raises(ValueError):
        check_line("x" * 96)
