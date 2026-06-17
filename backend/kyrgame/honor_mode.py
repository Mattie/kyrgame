from dataclasses import dataclass
from typing import Any

from . import modern_features


@dataclass(frozen=True)
class HonorModePolicy:
    force_honor_mode: bool = False
    default_honor_mode: bool = True

    def stored_creation_value(self, requested: bool | None) -> bool:
        if self.force_honor_mode:
            return True
        if requested is None:
            return self.default_honor_mode
        return bool(requested)

    def effective_honor_mode(self, player: Any, feature_id: str) -> bool:
        modern_features.require_feature(feature_id)
        if self.force_honor_mode:
            return True
        return bool(getattr(player, "honor_mode", self.default_honor_mode))

    def modern_feature_enabled(self, player: Any, feature_id: str) -> bool:
        return not self.effective_honor_mode(player, feature_id)

    def runtime_payload(self) -> dict:
        return {
            "force_honor_mode": self.force_honor_mode,
            "default_honor_mode": self.default_honor_mode,
            "selectable_honor_mode": not self.force_honor_mode,
            "modern_features": modern_features.public_feature_payloads(),
        }
