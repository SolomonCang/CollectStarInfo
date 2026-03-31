from __future__ import annotations

import csv
from io import StringIO
import json
import re
import time

import requests

from ..models import PlanetRecord, SimbadRecord


class PlanetClient:

    def __init__(self, timeout_sec: int = 30) -> None:
        self._timeout_sec = timeout_sec
        self._endpoint = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
        self._max_retries = 3

    @staticmethod
    def _to_float(value: str | None) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: str | None) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_name_for_match(name: str) -> str:
        return re.sub(r"\s+", "", name).strip().lower()

    @staticmethod
    def _planet_name_variants(target: str,
                              simbad: SimbadRecord | None) -> list[str]:
        candidates: list[str] = [target]

        if simbad is not None and simbad.object_name:
            object_name = str(simbad.object_name).strip()
            if object_name and object_name not in candidates:
                candidates.append(object_name)

            if object_name.upper().startswith("NAME "):
                without_prefix = object_name[5:].strip()
                if without_prefix and without_prefix not in candidates:
                    candidates.append(without_prefix)

        expanded: list[str] = []
        for name in candidates:
            expanded.append(name)
            compact = re.sub(r"\s+", "", name)
            if compact != name:
                expanded.append(compact)

        unique: list[str] = []
        seen: set[str] = set()
        for name in expanded:
            key = name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(name.strip())
        return unique

    def _query_by_planet_name(self, planet_name: str) -> PlanetRecord | None:
        normalized = self._normalize_name_for_match(planet_name)
        escaped = normalized.replace("'", "''")

        query = (
            "SELECT TOP 1 pl_name, hostname, pl_orbper, pl_rade, pl_bmasse, "
            "pl_orbsmax, pl_eqt, pl_insol, discoverymethod, disc_year, disc_facility "
            "FROM pscomppars "
            f"WHERE lower(replace(pl_name, ' ', '')) = '{escaped}'")

        response = None
        for attempt in range(self._max_retries):
            try:
                response = requests.get(
                    self._endpoint,
                    params={
                        "query": query,
                        "format": "csv"
                    },
                    timeout=self._timeout_sec,
                )
                if response.ok:
                    break
            except requests.RequestException:
                response = None

            if attempt < self._max_retries - 1:
                time.sleep(1.0)

        if response is None or not response.ok:
            return None

        reader = csv.DictReader(StringIO(response.text))
        rows = list(reader)
        if not rows:
            return None

        row = rows[0]
        planet = str(row.get("pl_name") or "").strip() or planet_name
        host = str(row.get("hostname") or "").strip() or None

        return PlanetRecord(
            planet_name=planet,
            host_name=host,
            orbital_period_days=self._to_float(row.get("pl_orbper")),
            radius_earth=self._to_float(row.get("pl_rade")),
            mass_earth=self._to_float(row.get("pl_bmasse")),
            semi_major_axis_au=self._to_float(row.get("pl_orbsmax")),
            equilibrium_temp_k=self._to_float(row.get("pl_eqt")),
            insolation_flux_earth=self._to_float(row.get("pl_insol")),
            discovery_method=(str(row.get("discoverymethod") or "").strip() or None),
            discovery_year=self._to_int(row.get("disc_year")),
            discovery_facility=(str(row.get("disc_facility") or "").strip() or None),
        )

    def _request(self, query: str, output_format: str) -> requests.Response | None:
        response = None
        for attempt in range(self._max_retries):
            try:
                response = requests.get(
                    self._endpoint,
                    params={
                        "query": query,
                        "format": output_format,
                    },
                    timeout=self._timeout_sec,
                )
                if response.ok:
                    return response
            except requests.RequestException:
                response = None

            if attempt < self._max_retries - 1:
                time.sleep(1.0)

        return response

    @staticmethod
    def _extract_reference_link(html: str) -> tuple[str | None, str | None, str | None]:
        if not html:
            return None, None, None

        href_match = re.search(r'href=([^\s>]+)', html, flags=re.IGNORECASE)
        label_match = re.search(r'>([^<]+)</a>', html, flags=re.IGNORECASE)
        bibcode_match = re.search(r'/abs/([^/]+)/abstract', html, flags=re.IGNORECASE)

        href = href_match.group(1).strip('"\'') if href_match else None
        label = label_match.group(1).strip() if label_match else None
        bibcode = bibcode_match.group(1).strip() if bibcode_match else None
        return bibcode, label, href

    @staticmethod
    def _reference_role_label(field_name: str) -> str:
        mapping = {
            "pl_refname": "planet parameters",
            "disc_refname": "discovery",
            "st_refname": "stellar parameters",
            "sy_refname": "system parameters",
        }
        return mapping.get(field_name, field_name)

    def _query_archive_references_by_planet_name(
        self,
        planet_name: str,
    ) -> list[dict[str, str | list[str]]]:
        normalized = self._normalize_name_for_match(planet_name)
        escaped = normalized.replace("'", "''")
        query = (
            "SELECT TOP 1 pl_name, hostname, pl_refname, disc_refname, st_refname, sy_refname "
            "FROM ps "
            f"WHERE lower(replace(pl_name, ' ', '')) = '{escaped}'"
        )

        response = self._request(query=query, output_format="json")
        if response is None or not response.ok:
            return []

        try:
            rows = json.loads(response.text)
        except json.JSONDecodeError:
            return []

        if not isinstance(rows, list) or not rows:
            return []

        row = rows[0]
        if not isinstance(row, dict):
            return []

        references: list[dict[str, str | list[str]]] = []
        seen_keys: set[str] = set()
        for field_name in ("pl_refname", "disc_refname", "st_refname", "sy_refname"):
            raw_value = str(row.get(field_name) or "").strip()
            if not raw_value:
                continue

            bibcode, label, href = self._extract_reference_link(raw_value)
            ref_key = (bibcode or label or raw_value).strip().lower()
            if not ref_key or ref_key in seen_keys:
                continue
            seen_keys.add(ref_key)

            item: dict[str, str | list[str]] = {
                "title": label or raw_value,
                "journal": "NASA Exoplanet Archive",
                "source_database": "NASA Exoplanet Archive",
                "reference_role": self._reference_role_label(field_name),
            }
            if bibcode:
                item["bibcode"] = bibcode
                year_match = re.match(r'^(\d{4})', bibcode)
                if year_match:
                    item["year"] = year_match.group(1)
            if href:
                item["url"] = href

            references.append(item)

        return references

    def query(self, target: str,
              simbad: SimbadRecord | None) -> PlanetRecord | None:
        for name in self._planet_name_variants(target, simbad):
            record = self._query_by_planet_name(name)
            if record is not None:
                return record
        return None

    def query_references(
        self,
        target: str,
        simbad: SimbadRecord | None,
    ) -> list[dict[str, str | list[str]]]:
        for name in self._planet_name_variants(target, simbad):
            references = self._query_archive_references_by_planet_name(name)
            if references:
                return references
        return []
