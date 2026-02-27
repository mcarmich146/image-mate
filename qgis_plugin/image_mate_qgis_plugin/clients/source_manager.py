from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .merlin_sentinel2_client import MerlinSentinel2Client, normalize_merlin_item
from .satellogic_client import SatellogicClient, normalize_item

SOURCE_SATELLOGIC = "satellogic"
SOURCE_MERLIN_S2 = "merlin-s2"
DEFAULT_SOURCE_ID = SOURCE_SATELLOGIC


@dataclass
class SourceInfo:
    source_id: str
    title: str
    enabled: bool
    supports_contracts: bool
    default_collection_id: str
    aliases: list[str]


class SourceManager:
    def __init__(self, satellogic_client: SatellogicClient, merlin_client: MerlinSentinel2Client):
        self.satellogic_client = satellogic_client
        self.merlin_client = merlin_client
        self._sources: dict[str, SourceInfo] = {
            SOURCE_SATELLOGIC: SourceInfo(
                source_id=SOURCE_SATELLOGIC,
                title="NewSat Constellation",
                enabled=True,
                supports_contracts=True,
                default_collection_id="l1d-sr",
                aliases=["satl"],
            ),
            SOURCE_MERLIN_S2: SourceInfo(
                source_id=SOURCE_MERLIN_S2,
                title="Merlin (Sentinel-2)",
                enabled=bool(self.merlin_client.enabled),
                supports_contracts=False,
                default_collection_id=(self.merlin_client.default_collections[0] if self.merlin_client.default_collections else "sentinel-2-l2a"),
                aliases=["merlin", "sentinel-2", "s2", "cdse"],
            ),
        }
        self._alias_map: dict[str, str] = {}
        for src_id, info in self._sources.items():
            self._alias_map[src_id] = src_id
            for alias in info.aliases:
                self._alias_map[alias] = src_id

    def normalize_source_id(self, source_id: str | None) -> str:
        key = (source_id or "").strip().lower()
        if not key:
            return DEFAULT_SOURCE_ID
        return self._alias_map.get(key, key)

    def source_info(self, source_id: str | None) -> SourceInfo:
        normalized = self.normalize_source_id(source_id)
        return self._sources.get(normalized, self._sources[DEFAULT_SOURCE_ID])

    def has_source(self, source_id: str | None) -> bool:
        normalized = self.normalize_source_id(source_id)
        return normalized in self._sources

    def list_sources(self) -> list[dict[str, Any]]:
        rows = []
        for info in self._sources.values():
            rows.append(
                {
                    "source_id": info.source_id,
                    "title": info.title,
                    "enabled": bool(info.enabled),
                    "supports_contracts": bool(info.supports_contracts),
                    "default_collection_id": info.default_collection_id,
                }
            )
        return rows

    def split_item_id(self, item_id: str) -> tuple[str, str]:
        value = (item_id or "").strip()
        if ":" not in value:
            return DEFAULT_SOURCE_ID, value
        prefix, suffix = value.split(":", 1)
        source_id = self.normalize_source_id(prefix)
        if source_id in self._sources and suffix:
            return source_id, suffix
        return DEFAULT_SOURCE_ID, value

    def infer_source_id_from_url(self, url: str, source_hint: str | None = None) -> str:
        hint = self.normalize_source_id(source_hint)
        if hint in self._sources and self._sources[hint].enabled:
            return hint
        host = (urlparse(url).netloc or "").strip().lower()
        if "dataspace.copernicus" in host or host.endswith("copernicus.eu"):
            return SOURCE_MERLIN_S2
        if "sentinel-hub.com" in host:
            return SOURCE_MERLIN_S2
        return DEFAULT_SOURCE_ID

    def list_contracts(self, source_id: str | None) -> list[dict[str, Any]]:
        src = self.normalize_source_id(source_id)
        if src == SOURCE_SATELLOGIC:
            return self.satellogic_client.list_contracts()
        if src == SOURCE_MERLIN_S2:
            return self.merlin_client.list_contracts()
        raise ValueError(f"Unknown source_id '{source_id}'")

    def list_collections(self, source_id: str | None, contract_id: str | None = None) -> list[dict[str, Any]]:
        src = self.normalize_source_id(source_id)
        if src == SOURCE_SATELLOGIC:
            return self.satellogic_client.list_collections(contract_id=contract_id)
        if src == SOURCE_MERLIN_S2:
            return self.merlin_client.list_collections()
        raise ValueError(f"Unknown source_id '{source_id}'")

    def search(
        self,
        *,
        source_id: str | None,
        geometry: dict[str, Any],
        start_date: str,
        end_date: str,
        collection_id: str,
        contract_id: str | None,
        limit: int,
        max_cloud_cover: float | None,
        satellite_name: str | None = None,
        min_gsd: float | None = None,
        max_gsd: float | None = None,
    ) -> list[dict[str, Any]]:
        src = self.normalize_source_id(source_id)
        if src == SOURCE_SATELLOGIC:
            features = self.satellogic_client.search(
                geometry=geometry,
                start_date=start_date,
                end_date=end_date,
                collection_id=collection_id,
                contract_id=contract_id,
                limit=limit,
                max_cloud_cover=max_cloud_cover,
                satellite_name=satellite_name,
                min_gsd=min_gsd,
                max_gsd=max_gsd,
            )
            items = [normalize_item(feature) for feature in features]
            for item in items:
                item["source_id"] = SOURCE_SATELLOGIC
            return items
        if src == SOURCE_MERLIN_S2:
            features = self.merlin_client.search(
                geometry=geometry,
                start_date=start_date,
                end_date=end_date,
                collection_id=collection_id,
                limit=limit,
                max_cloud_cover=max_cloud_cover,
                satellite_name=satellite_name,
                min_gsd=min_gsd,
                max_gsd=max_gsd,
            )
            return [normalize_merlin_item(feature, source_id=SOURCE_MERLIN_S2) for feature in features]
        raise ValueError(f"Unknown source_id '{source_id}'")

    def item_by_id(
        self,
        item_id: str,
        *,
        source_id: str | None = None,
        contract_id: str | None = None,
        collection_id: str | None = None,
    ) -> dict[str, Any] | None:
        hint = self.normalize_source_id(source_id)
        if hint == SOURCE_SATELLOGIC and ":" in (item_id or ""):
            inferred_source, native_id = self.split_item_id(item_id)
            if inferred_source != SOURCE_SATELLOGIC:
                hint = inferred_source
                item_id = native_id
        elif hint != SOURCE_SATELLOGIC and ":" in (item_id or ""):
            _, native_id = self.split_item_id(item_id)
            item_id = native_id

        if hint == SOURCE_SATELLOGIC:
            feature = self.satellogic_client.item_by_id(item_id, contract_id=contract_id)
            if not feature:
                return None
            item = normalize_item(feature)
            item["source_id"] = SOURCE_SATELLOGIC
            return item
        if hint == SOURCE_MERLIN_S2:
            feature = self.merlin_client.item_by_id(item_id, collection_id=collection_id)
            if not feature:
                return None
            return normalize_merlin_item(feature, source_id=SOURCE_MERLIN_S2)
        raise ValueError(f"Unknown source_id '{source_id}'")

    def auth_headers_for_url(self, url: str, *, contract_id: str | None = None, source_hint: str | None = None) -> dict[str, str]:
        src = self.infer_source_id_from_url(url, source_hint=source_hint)
        if src == SOURCE_MERLIN_S2:
            return self.merlin_client.auth_headers_for_url(url)
        return self.satellogic_client.auth_headers(contract_id=contract_id)

    def download_bytes(self, url: str, *, contract_id: str | None = None, source_hint: str | None = None) -> bytes:
        src = self.infer_source_id_from_url(url, source_hint=source_hint)
        if src == SOURCE_MERLIN_S2:
            return self.merlin_client.download_bytes(url)
        return self.satellogic_client.download_bytes(url, contract_id=contract_id)
