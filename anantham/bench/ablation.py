"""Ablation study (section 8): the same scenarios under cumulative component switches.

Variants (see ``scenarios.ABLATION``):
classical only · classical + Kalman · CNN only · hybrid · hybrid + identity gate ·
+ prediction / feed-forward · full system (adds adaptive R/Q, uncertainty-scaled gains
and the local recovery spiral).

Run with ``anantham bench --scenarios all --ablation``; results are written to
``ablation_summary.csv/.md``.
"""

from .run_bench import ablation_markdown, ablation_table
from .scenarios import ABLATION

__all__ = ["ABLATION", "ablation_table", "ablation_markdown"]
