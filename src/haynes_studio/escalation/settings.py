"""Source defaults for CR-30. Automatic authorization defaults off."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    authorization: str = "person"
    per_production_per_day: int = 1
    total_per_day: int = 2

    def __post_init__(self):
        if self.authorization != "automatic":
            object.__setattr__(self, "authorization", "person")
        if not 0 <= self.per_production_per_day <= self.total_per_day <= 2**31 - 1:
            raise ValueError("Escalation caps require 0 <= per-production <= total <= 2**31 - 1")

    @classmethod
    def from_environment(cls):
        return cls(
            os.getenv("STUDIO_ESCALATION_AUTHORIZATION", "person"),
            int(os.getenv("STUDIO_ESCALATION_PER_PRODUCTION_PER_DAY", "1")),
            int(os.getenv("STUDIO_ESCALATION_TOTAL_PER_DAY", "2")),
        )
