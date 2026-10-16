"""Registry of analysis methods. Add a new method by subclassing `Method` and registering it here."""
from .base import TASK_TYPES, Assessment, Finding, Method, Recommendation, Stage
from .exploratory import AnomalyMethod, ComparisonMethod, DescriptiveMethod, SegmentationMethod
from .hypothesis import HypothesisTestMethod
from .modeling import ClassificationMethod, RegressionMethod
from .profit_change import ProfitChangeMethod
from .timeseries import ForecastMethod

REGISTRY: dict[str, Method] = {m.task_type: m for m in [
    DescriptiveMethod(), ComparisonMethod(), HypothesisTestMethod(), ClassificationMethod(), RegressionMethod(),
    ForecastMethod(), SegmentationMethod(), AnomalyMethod(), ProfitChangeMethod(),
]}


def get_method(task_type: str) -> Method:
    if task_type not in REGISTRY:
        raise KeyError(f"No analysis method registered for task type '{task_type}'")
    return REGISTRY[task_type]


__all__ = ["REGISTRY", "TASK_TYPES", "get_method", "Method", "Stage", "Assessment", "Finding", "Recommendation"]
