"""#331: the root conftest keeps every test away from the repo's real raw/ and data/."""

from core import io


def test_tests_never_see_real_folders():
    assert io.raw_root() != io.ROOT / "raw"
    assert not io.stage_path("aggregate/observed").is_relative_to(io.ROOT / "data")
