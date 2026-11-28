import sys

from validate import run
from validate.detect_prob import _report as detect_prob_report

run(quick="--quick" in sys.argv[1:])  # make validate-quick (#343)
detect_prob_report()  # reports/detect_prob.json (#349)
