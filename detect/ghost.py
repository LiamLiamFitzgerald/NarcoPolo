"""Azimuth-ambiguity ghost rule."""


def ghost_offset_m(meta):  # stub, issue #5
    return (4000, 8000)


def azimuth_heading(meta) -> float:  # stub, issue #5
    return 0.0


def is_ghost(cand, img, heading, offset, tol_m=200, db=20) -> bool:  # stub, issue #5
    return False
