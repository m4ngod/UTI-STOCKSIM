from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from strategy_diagnostics.market_paths import (
    MarketPathCacheCompatibility,
    MarketPathCacheFallbackState,
    MarketPathCacheHealthSnapshot,
    MarketPathCacheRefreshResult,
    MaterializedMarketPath,
    unobserved_market_path_cache_health,
)


class ApplicationDrivenCacheStore:
    """Public artifact-store port used to drive health via Application calls."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        fallback_on_first_put: bool = False,
        incompatible_on_first_put: bool = False,
        incompatible_on_second_put: bool = False,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._fallback_on_first_put = fallback_on_first_put
        self._incompatible_on_first_put = incompatible_on_first_put
        self._incompatible_on_second_put = incompatible_on_second_put
        self._paths: dict[str, MaterializedMarketPath] = {}
        self._health = unobserved_market_path_cache_health()
        self._put_count = 0
        self._fail_next_list = False

    def put(self, path: MaterializedMarketPath) -> MaterializedMarketPath:
        if (
            self._incompatible_on_first_put and self._put_count == 0
        ) or (
            self._incompatible_on_second_put and self._put_count >= 1
        ):
            self._health = MarketPathCacheHealthSnapshot(
                generation=self._health.generation,
                observed_at=self._aware_now(),
                fallback=MarketPathCacheFallbackState.UNAVAILABLE,
                last_refresh_result=MarketPathCacheRefreshResult.FAILED,
                compatibility=MarketPathCacheCompatibility.INCOMPATIBLE,
                affected_artifact_count=max(len(self._paths), 1),
            )
            raise ValueError("incompatible cache publication")
        is_new = path.artifact_hash not in self._paths
        self._paths[path.artifact_hash] = path
        self._put_count += 1
        self._record_success(
            fallback=(
                MarketPathCacheFallbackState.ACTIVE
                if self._fallback_on_first_put and self._put_count == 1
                else MarketPathCacheFallbackState.PRIMARY
            ),
            refresh_result=(
                MarketPathCacheRefreshResult.FALLBACK_SUCCEEDED
                if self._fallback_on_first_put and self._put_count == 1
                else MarketPathCacheRefreshResult.SUCCEEDED
            ),
            generation_changed=is_new,
        )
        return path

    def get(self, artifact_hash: str) -> MaterializedMarketPath:
        try:
            path = self._paths[artifact_hash]
        except KeyError as error:
            self._record_failure(MarketPathCacheCompatibility.COMPATIBLE)
            raise KeyError("unknown Materialized Market Path artifact") from error
        self._record_success()
        return path

    def get_verified(self, artifact_hash: str) -> MaterializedMarketPath:
        return self.get(artifact_hash)

    def list_paths(self) -> tuple[MaterializedMarketPath, ...]:
        if self._fail_next_list:
            self._fail_next_list = False
            self._record_failure(MarketPathCacheCompatibility.COMPATIBLE)
            raise OSError("cache listing unavailable")
        paths = tuple(
            sorted(self._paths.values(), key=lambda item: item.artifact_hash)
        )
        self._record_success()
        return paths

    def diagnostic_cache_health(self) -> MarketPathCacheHealthSnapshot:
        return self._health

    def fail_next_application_list(self) -> None:
        """Arrange a backend fault; the Application call records the outcome."""

        self._fail_next_list = True

    def _record_success(
        self,
        *,
        fallback: MarketPathCacheFallbackState = (
            MarketPathCacheFallbackState.PRIMARY
        ),
        refresh_result: MarketPathCacheRefreshResult = (
            MarketPathCacheRefreshResult.SUCCEEDED
        ),
        generation_changed: bool = False,
    ) -> None:
        generation = self._health.generation
        if generation == 0:
            generation = 1
        elif generation_changed:
            generation += 1
        self._health = MarketPathCacheHealthSnapshot(
            generation=generation,
            observed_at=self._aware_now(),
            fallback=fallback,
            last_refresh_result=refresh_result,
            compatibility=MarketPathCacheCompatibility.COMPATIBLE,
            affected_artifact_count=len(self._paths),
        )

    def _record_failure(
        self,
        compatibility: MarketPathCacheCompatibility,
    ) -> None:
        self._health = MarketPathCacheHealthSnapshot(
            generation=self._health.generation,
            observed_at=self._aware_now(),
            fallback=MarketPathCacheFallbackState.UNAVAILABLE,
            last_refresh_result=MarketPathCacheRefreshResult.FAILED,
            compatibility=compatibility,
            affected_artifact_count=len(self._paths),
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cache test clock must be timezone-aware")
        return value


__all__ = ["ApplicationDrivenCacheStore"]
