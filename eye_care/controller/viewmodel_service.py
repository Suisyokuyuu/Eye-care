from __future__ import annotations
from dataclasses import dataclass
from typing import Dict
from ..data.repository import Repository

@dataclass(frozen=True)
class ViewModel:
    local_date: str
    daily_usage: Dict[str, int]

class ViewModelService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def get_today(self, local_date: str) -> ViewModel:
        return ViewModel(local_date=local_date, daily_usage=self.repo.get_daily_usage(local_date))
