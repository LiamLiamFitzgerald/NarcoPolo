from core import io
from core.config import load
from sim.simulate import simulate

cfg, _ = load(io.CONFIG_PATH)
simulate(cfg, cfg["seed"])
