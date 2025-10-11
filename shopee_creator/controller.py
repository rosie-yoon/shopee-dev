from __future__ import annotations
from dataclasses import dataclass
from typing import List
import traceback
from . import creation_steps as steps

@dataclass
class StepLog:
    name: str
    ok: bool
    count: int | None = None
    error: str | None = None

class ShopeeCreator:
    """기존 creation_steps를 그대로 호출하는 얇은 러너"""
    def run(self, *, input_sheet_url: str) -> List[StepLog]:
        logs: List[StepLog] = []
        pipeline = [
            ("C1 Collect", getattr(steps, "run_c1_collect", None)),
            ("C2 To TEM", getattr(steps, "run_c2_tem", None)),
            ("C3 FDA", getattr(steps, "run_c3_fda", None)),
            ("C4 Price", getattr(steps, "run_c4_price", None)),
            ("C5 Images", getattr(steps, "run_c5_images", None)),
            ("C6 Stock/Weight/Brand", getattr(steps, "run_c6_swb", None)),
        ]
        for name, fn in pipeline:
            if fn is None:
                logs.append(StepLog(name=name, ok=False, error="Not implemented"))
                continue
            try:
                result = fn(input_sheet_url=input_sheet_url)  # 기존 시그니처 가정
                count = getattr(result, "count", None) if result is not None else None
                logs.append(StepLog(name=name, ok=True, count=count))
            except Exception as e:
                logs.append(StepLog(name=name, ok=False, error=f"{e}\n{traceback.format_exc()}"))
                break
        return logs
