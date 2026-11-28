# `simulate` stays at sim.simulate.simulate: re-exporting it here would hide the sim.simulate module
from sim.patrol import patrol_outcome

__all__ = ["patrol_outcome"]
