"""Global, versioned threshold profiles for CRC, CSR, and SSR readout."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

import math

from .serialization import parse_datetime, to_primitive


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ThresholdRule:
    comparison: str
    counts: float
    exclusion_width: float = 0.0
    channel: str = "SPCM1"

    def __post_init__(self) -> None:
        if self.comparison not in ("<", ">", "<=", ">="):
            raise ValueError("Unsupported threshold comparison: {!r}".format(self.comparison))
        if self.exclusion_width < 0:
            raise ValueError("Threshold exclusion_width must not be negative")
        if not math.isfinite(self.counts) or not math.isfinite(self.exclusion_width):
            raise ValueError("Threshold values must be finite")
        if not self.channel:
            raise ValueError("Threshold channel must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ThresholdRule":
        return cls(
            comparison=value["comparison"],
            counts=float(value["counts"]),
            exclusion_width=float(value.get("exclusion_width", 0.0)),
            channel=value.get("channel", "SPCM1"),
        )


@dataclass(frozen=True)
class ReadoutThresholdProfile:
    """Setup-wide thresholds referenced by experiment readout steps."""

    name: str
    rules: Mapping[str, ThresholdRule]
    version: int = 1
    updated_at: datetime = field(default_factory=_utc_now)
    source_run_id: str = ""
    notes: str = ""

    REQUIRED_RULES = frozenset(("crc_accept", "crc_repump", "csr_accept", "ssr_e1", "ssr_e2"))

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Threshold profile name must not be empty")
        if self.version < 1:
            raise ValueError("Threshold profile version must be positive")
        rules = {
            key: value if isinstance(value, ThresholdRule) else ThresholdRule.from_dict(value)
            for key, value in self.rules.items()
        }
        missing = self.REQUIRED_RULES.difference(rules)
        if missing:
            raise ValueError("Threshold profile is missing rules: {}".format(sorted(missing)))
        object.__setattr__(self, "rules", rules)

    def resolve(self, reference: str) -> ThresholdRule:
        try:
            return self.rules[reference]
        except KeyError as exc:
            raise KeyError(
                "Threshold rule {!r} does not exist in profile {!r}".format(reference, self.name)
            ) from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
            "source_run_id": self.source_run_id,
            "notes": self.notes,
            "rules": {name: rule.to_dict() for name, rule in self.rules.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReadoutThresholdProfile":
        return cls(
            name=value["name"],
            version=int(value.get("version", 1)),
            updated_at=parse_datetime(value.get("updated_at", _utc_now()), "updated_at"),
            source_run_id=value.get("source_run_id", ""),
            notes=value.get("notes", ""),
            rules={
                name: ThresholdRule.from_dict(rule)
                for name, rule in value.get("rules", {}).items()
            },
        )


@dataclass(frozen=True)
class ThresholdSnapshot:
    profile: ReadoutThresholdProfile
    resolved_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_at": self.resolved_at.isoformat(),
            "profile": self.profile.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ThresholdSnapshot":
        return cls(
            resolved_at=parse_datetime(value["resolved_at"], "resolved_at"),
            profile=ReadoutThresholdProfile.from_dict(value["profile"]),
        )


def default_threshold_profile() -> ReadoutThresholdProfile:
    """Conservative defaults matching the current Qinu script conventions."""

    return ReadoutThresholdProfile(
        name="default",
        rules={
            "crc_accept": ThresholdRule(">", 10),
            "crc_repump": ThresholdRule("<", 2),
            "csr_accept": ThresholdRule(">", 1),
            "ssr_e1": ThresholdRule(">", 1),
            "ssr_e2": ThresholdRule("<", 1),
        },
        notes="Initial migration defaults; calibrate for the active setup before production use.",
    )


class ThresholdRegistry:
    """In-memory versioned registry used by the Qudi calibration module."""

    def __init__(self, profiles=None, default_profile: str = "default") -> None:
        profiles = [default_threshold_profile()] if profiles is None else list(profiles)
        self._profiles = {}
        for profile in profiles:
            self.put(profile, allow_same_version=True)
        self.default_profile = default_profile
        if self.default_profile not in self._profiles:
            raise KeyError("Default threshold profile {!r} does not exist".format(default_profile))

    @property
    def profiles(self) -> Mapping[str, ReadoutThresholdProfile]:
        return {
            name: versions[max(versions)] for name, versions in self._profiles.items()
        }

    def versions(self, name: str):
        try:
            return tuple(sorted(self._profiles[name]))
        except KeyError as exc:
            raise KeyError("Unknown threshold profile: {!r}".format(name)) from exc

    def put(self, profile: ReadoutThresholdProfile, allow_same_version: bool = False) -> None:
        versions = self._profiles.setdefault(profile.name, {})
        if versions:
            latest_version = max(versions)
            if profile.version < latest_version:
                raise ValueError("A threshold profile cannot move to an older version")
            if profile.version in versions and not allow_same_version:
                raise ValueError(
                    "Updating profile {!r} requires a higher version".format(profile.name)
                )
        versions[profile.version] = profile

    def get(self, name: Optional[str] = None, version: Optional[int] = None) -> ReadoutThresholdProfile:
        name = self.default_profile if name is None else name
        try:
            versions = self._profiles[name]
        except KeyError as exc:
            raise KeyError("Unknown threshold profile: {!r}".format(name)) from exc
        resolved_version = max(versions) if version is None else version
        try:
            return versions[resolved_version]
        except KeyError as exc:
            raise KeyError(
                "Threshold profile {!r} has versions {}, requested {}".format(
                    name, sorted(versions), resolved_version
                )
            ) from exc

    def snapshot(self, name: Optional[str] = None, version: Optional[int] = None) -> ThresholdSnapshot:
        return ThresholdSnapshot(profile=self.get(name=name, version=version))

    def snapshot_for_experiment(self, experiment) -> ThresholdSnapshot:
        """Resolve and validate every threshold referenced by an experiment."""

        snapshot = self.snapshot(
            name=experiment.threshold_profile,
            version=experiment.threshold_version,
        )
        for step in experiment.readout:
            snapshot.profile.resolve(step.threshold_ref)
        return snapshot

    def remove(self, name: str) -> None:
        if name == self.default_profile:
            raise ValueError("The default threshold profile cannot be removed")
        del self._profiles[name]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_profile": self.default_profile,
            "profiles": {
                name: {
                    "latest_version": max(versions),
                    "versions": {
                        str(version): profile.to_dict()
                        for version, profile in sorted(versions.items())
                    },
                }
                for name, versions in sorted(self._profiles.items())
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ThresholdRegistry":
        profiles = []
        for profile_value in value.get("profiles", {}).values():
            # Accept the initial migration schema, which stored only the latest
            # profile, as well as the version-history schema.
            if "versions" in profile_value:
                profiles.extend(
                    ReadoutThresholdProfile.from_dict(version_value)
                    for version_value in profile_value["versions"].values()
                )
            else:
                profiles.append(ReadoutThresholdProfile.from_dict(profile_value))
        return cls(profiles=profiles, default_profile=value.get("default_profile", "default"))
