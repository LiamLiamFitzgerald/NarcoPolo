import os
import tempfile

# Detectors read reports/cusum_h.json at import (D2); tests must not depend on a local report.
os.environ["NARCO_REPORTS"] = tempfile.mkdtemp(prefix="narco-reports-")
