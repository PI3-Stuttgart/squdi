"""Deterministic planning of QUA, host, and recompilation scan axes."""

import itertools
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

import numpy as np

from .models import AxisExecution, ExperimentSpec, ScanAxis
from .serialization import to_primitive


@dataclass(frozen=True)
class ExecutionBlock:
    """One host/recompilation context containing all inner QUA axes."""

    index: int
    host_values: Mapping[str, Any]
    recompile_values: Mapping[str, Any]
    qua_axes: Tuple[ScanAxis, ...]

    @property
    def qua_points(self) -> int:
        return int(np.prod([len(axis.values) for axis in self.qua_axes], dtype=int))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "host_values": to_primitive(dict(self.host_values)),
            "recompile_values": to_primitive(dict(self.recompile_values)),
            "qua_axes": [axis.to_dict() for axis in self.qua_axes],
            "qua_points": self.qua_points,
        }


@dataclass(frozen=True)
class ScanExecutionPlan:
    axes: Tuple[ScanAxis, ...]
    blocks: Tuple[ExecutionBlock, ...]

    @property
    def total_points(self) -> int:
        return int(np.prod([len(axis.values) for axis in self.axes], dtype=int))

    @property
    def program_executions(self) -> int:
        return len(self.blocks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axes": [axis.to_dict() for axis in self.axes],
            "blocks": [block.to_dict() for block in self.blocks],
            "total_points": self.total_points,
            "program_executions": self.program_executions,
        }


class ScanPlanner:
    """Resolve explicit scan policies and construct ordered execution blocks.

    Recipes provide policies for axes declared with ``execution='auto'``. This
    is intentionally strict: silently treating a magnet or laser-setpoint axis
    as a QUA loop can produce physically incorrect experiments.
    """

    def __init__(self, axis_policies: Mapping[str, AxisExecution] = None) -> None:
        self.axis_policies = {
            name: AxisExecution(execution)
            for name, execution in (axis_policies or {}).items()
        }
        if any(value == AxisExecution.AUTO for value in self.axis_policies.values()):
            raise ValueError("Scan planner policies must resolve to a concrete execution mode")

    def plan(self, experiment: ExperimentSpec) -> ScanExecutionPlan:
        resolved_axes = tuple(self._resolve_axis(axis) for axis in experiment.scan_axes)
        qua_axes = tuple(axis for axis in resolved_axes if axis.execution == AxisExecution.QUA)
        outer_axes = tuple(axis for axis in resolved_axes if axis.execution != AxisExecution.QUA)

        combinations = itertools.product(*(axis.values for axis in outer_axes)) if outer_axes else ((),)
        blocks = []
        for index, combination in enumerate(combinations):
            values = dict(zip((axis.name for axis in outer_axes), combination))
            host_values = {
                axis.name: values[axis.name]
                for axis in outer_axes
                if axis.execution == AxisExecution.HOST
            }
            recompile_values = {
                axis.name: values[axis.name]
                for axis in outer_axes
                if axis.execution == AxisExecution.RECOMPILE
            }
            blocks.append(
                ExecutionBlock(
                    index=index,
                    host_values=host_values,
                    recompile_values=recompile_values,
                    qua_axes=qua_axes,
                )
            )

        plan = ScanExecutionPlan(axes=resolved_axes, blocks=tuple(blocks))
        if plan.total_points != sum(block.qua_points for block in plan.blocks):
            raise RuntimeError("Scan plan does not cover every experiment point exactly once")
        return plan

    def _resolve_axis(self, axis: ScanAxis) -> ScanAxis:
        if axis.execution != AxisExecution.AUTO:
            return axis
        try:
            execution = self.axis_policies[axis.name]
        except KeyError as exc:
            raise ValueError(
                "Scan axis {!r} uses execution='auto', but its recipe did not provide a policy".format(
                    axis.name
                )
            ) from exc
        return ScanAxis(
            name=axis.name,
            values=axis.values,
            unit=axis.unit,
            execution=execution,
        )
