"""SQLModel tables, one module per aggregate.

Importing this package registers every table on ``SQLModel.metadata`` — both
Alembic's autogenerate and :func:`gaugix.db.create_all` depend on that.
"""

from gaugix.models.artifacts import Artifact
from gaugix.models.base import TimestampMixin, dump_json, load_json, utcnow
from gaugix.models.cases import AppSetting, EvalCase, EvalSet, SetMembership
from gaugix.models.executors import (
    Executor,
    HarnessProfile,
    ModelProfile,
    default_executor_name,
)
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.models.scores import Score

__all__ = [
    "AppSetting",
    "Artifact",
    "Attempt",
    "EvalCase",
    "EvalSet",
    "Executor",
    "HarnessProfile",
    "ModelProfile",
    "Run",
    "RunItem",
    "Score",
    "SetMembership",
    "TimestampMixin",
    "default_executor_name",
    "dump_json",
    "load_json",
    "utcnow",
]
