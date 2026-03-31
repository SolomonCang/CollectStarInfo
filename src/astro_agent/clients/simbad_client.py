from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from astropy.coordinates import Angle
import astropy.units as u
from astroquery.simbad import Simbad

from ..models import SimbadRecord


def _find_col(row, *candidates: str):
    keys = {str(k).upper(): k for k in row.colnames}
    for name in candidates:
        key = keys.get(name.upper())
        if key is not None:
            return row[key]
    return None


class SimbadClient:

    _BASE_VOTABLE_FIELDS = (
        "ra",
        "dec",
        "sp",
        "otype",
        "ids",
        "plx_value",
        "plx_err",
    )

    _SERVERS = (
        "simbad.cds.unistra.fr",
        "simbad.harvard.edu",
    )

    def __init__(self, reference_time_range: str = "all") -> None:
        self._simbad = self._build_resilient_simbad_client(include_flux_g=True)
        self._fallback_simbad = self._build_resilient_simbad_client(
            include_flux_g=False)
        self._reference_time_range = reference_time_range

    def _build_resilient_simbad_client(self, include_flux_g: bool) -> Simbad:
        last_error: Exception | None = None
        for server in self._SERVERS:
            try:
                custom = Simbad()
                custom.server = server
                fields = list(self._BASE_VOTABLE_FIELDS)
                if include_flux_g:
                    fields.append("G")
                custom.add_votable_fields(*fields)
                return custom
            except Exception as exc:
                last_error = exc
                continue

        # Final fallback: keep a basic client so queries can still proceed.
        basic = Simbad()
        if last_error is not None:
            print(
                f"[SIMBAD] fallback to basic client (no extra fields): {last_error}"
            )
        return basic

    @staticmethod
    def _query_object_with_fallbacks(
        clients: tuple[Simbad, ...],
        candidate: str,
    ):
        for client in clients:
            try:
                table = client.query_object(candidate)
            except Exception:
                continue
            if table is not None and len(table) > 0:
                return table
        return None

    @staticmethod
    def _parse_ra_deg(value: Any) -> float | None:
        numeric = SimbadClient._to_float(value)
        if numeric is not None:
            return numeric

        text = str(value).strip()
        if not text or text == "--":
            return None

        try:
            return float(Angle(text, unit=u.hourangle).degree)
        except Exception:
            return None

    @staticmethod
    def _parse_dec_deg(value: Any) -> float | None:
        numeric = SimbadClient._to_float(value)
        if numeric is not None:
            return numeric

        text = str(value).strip()
        if not text or text == "--":
            return None

        try:
            return float(Angle(text, unit=u.deg).degree)
        except Exception:
            return None

    @staticmethod
    def _normalize_target_name(target: str) -> str:
        # Normalize common Unicode dashes and strip trailing punctuation.
        text = target.strip()
        text = (text.replace("\u2010", "-").replace("\u2011", "-").replace(
            "\u2012", "-").replace("\u2013",
                                   "-").replace("\u2014",
                                                "-").replace("\u2212", "-"))
        return text.rstrip("。.,;:!?")

    @classmethod
    def _target_name_variants(cls, target: str) -> list[str]:
        normalized = cls._normalize_target_name(target)
        variants = [normalized]

        # Many exoplanets are indexed with an optional space before suffix.
        space_variant = re.sub(r"(?<=\d)([bcdefgh])$",
                               r" \1",
                               normalized,
                               flags=re.IGNORECASE)
        if space_variant != normalized:
            variants.append(space_variant)

        hyphen_space_variant = re.sub(
            r"(?<=\d)-([bcdefgh])$",
            r" \1",
            normalized,
            flags=re.IGNORECASE,
        )
        if hyphen_space_variant not in variants:
            variants.append(hyphen_space_variant)

        compact = re.sub(r"\s+", "", normalized)
        if compact and compact not in variants:
            variants.append(compact)

        unique: list[str] = []
        seen: set[str] = set()
        for item in variants:
            key = item.casefold().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item.strip())
        return unique

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text == "--":
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _distance_from_parallax(
        parallax_mas: float | None,
        parallax_err_mas: float | None,
    ) -> tuple[float | None, float | None]:
        if parallax_mas is None or parallax_mas <= 0:
            return None, None

        distance_pc = 1000.0 / parallax_mas
        if parallax_err_mas is None:
            return distance_pc, None

        distance_err_pc = 1000.0 * parallax_err_mas / (parallax_mas**2)
        return distance_pc, distance_err_pc

    def _query_references(self, target: str,
                          object_name: str) -> list[dict[str, Any]]:
        candidates: list[str] = [target]
        if object_name and object_name not in candidates:
            candidates.append(object_name)
        if object_name.upper().startswith("NAME "):
            without_prefix = object_name[5:].strip()
            if without_prefix and without_prefix not in candidates:
                candidates.append(without_prefix)

        for name in candidates:
            escaped = name.replace("'", "''")
            year_filter = ""
            if self._reference_time_range == "recent10":
                min_year = datetime.now(timezone.utc).year - 9
                year_filter = f" AND \"r\".\"year\" >= '{min_year}'"

            query = (
                "SELECT r.bibcode, \"r\".\"year\" AS pub_year, r.journal, "
                "r.title, r.abstract, h.obj_freq AS obj_freq, k.keyword "
                "FROM ident AS i "
                "JOIN has_ref AS h ON i.oidref = h.oidref "
                "JOIN ref AS \"r\" ON h.oidbibref = \"r\".oidbib "
                "LEFT JOIN keywords AS k ON \"r\".oidbib = k.oidbibref "
                f"WHERE i.id = '{escaped}' "
                f"{year_filter}"
                "ORDER BY obj_freq DESC")

            try:
                table = self._simbad.query_tap(query)
            except Exception:
                continue

            if table is None or len(table) == 0:
                continue

            refs_by_key: dict[str, dict[str, Any]] = {}
            ref_order: list[str] = []
            for row in table:
                bibcode = _find_col(row, "bibcode")
                year = _find_col(row, "pub_year")
                journal = _find_col(row, "journal")
                title = _find_col(row, "title")
                abstract = _find_col(row, "abstract")
                obj_freq = _find_col(row, "obj_freq")
                keyword = _find_col(row, "keyword")

                item: dict[str, Any] = {}

                if bibcode is not None and str(bibcode).strip() and str(
                        bibcode) != "--":
                    item["bibcode"] = str(bibcode).strip()
                if year is not None and str(year).strip() and str(
                        year) != "--":
                    item["year"] = str(year).strip()
                if journal is not None and str(journal).strip() and str(
                        journal) != "--":
                    item["journal"] = str(journal).strip()
                if title is not None and str(title).strip() and str(
                        title) != "--":
                    item["title"] = str(title).strip()
                if abstract is not None and str(abstract).strip() and str(
                        abstract) != "--":
                    item["abstract"] = str(abstract).strip()
                if obj_freq is not None and str(obj_freq).strip() and str(
                        obj_freq) != "--":
                    item["obj_freq"] = str(obj_freq).strip()
                if keyword is not None and str(keyword).strip() and str(
                        keyword) != "--":
                    item["keywords"] = [str(keyword).strip()]

                if item:
                    ref_key = str(item.get("bibcode") or "|").strip()
                    if ref_key == "|":
                        ref_key = "|".join([
                            str(item.get("year") or "").strip(),
                            str(item.get("journal") or "").strip(),
                            str(item.get("title") or "").strip(),
                        ])

                    existing = refs_by_key.get(ref_key)
                    if existing is None:
                        refs_by_key[ref_key] = item
                        ref_order.append(ref_key)
                        continue

                    existing_keywords = existing.get("keywords")
                    new_keywords = item.get("keywords")
                    if not isinstance(existing_keywords, list):
                        existing_keywords = []
                        existing["keywords"] = existing_keywords
                    if isinstance(new_keywords, list):
                        for value in new_keywords:
                            if value not in existing_keywords:
                                existing_keywords.append(value)

            refs = [refs_by_key[key] for key in ref_order]
            if refs:
                return refs

        return []

    def query(self, target: str) -> SimbadRecord | None:
        table = None
        query_name = target
        candidates = self._target_name_variants(target)
        for candidate in candidates:
            table = self._query_object_with_fallbacks(
                (self._simbad, self._fallback_simbad), candidate)
            if table is not None and len(table) > 0:
                query_name = candidate
                break

        if table is None or len(table) == 0:
            for candidate in candidates:
                try:
                    ids_table = self._simbad.query_objectids(candidate)
                except Exception:
                    continue

                if ids_table is None or len(ids_table) == 0:
                    continue

                colname = ids_table.colnames[0]
                for row in ids_table:
                    identifier = str(row[colname]).strip()
                    if not identifier:
                        continue
                    table = self._query_object_with_fallbacks(
                        (self._simbad, self._fallback_simbad), identifier)
                    if table is not None and len(table) > 0:
                        query_name = identifier
                        break

                if table is not None and len(table) > 0:
                    break

        if table is None or len(table) == 0:
            return None

        row = table[0]

        ra = _find_col(row, "RA_d", "RA")
        dec = _find_col(row, "DEC_d", "DEC")
        sp_type = _find_col(row, "SP_TYPE")
        object_type = _find_col(row, "OTYPE", "OTYPE_V")
        ids = _find_col(row, "IDS")
        main_id = _find_col(row, "MAIN_ID")
        parallax = _find_col(row, "PLX_VALUE", "PLX")
        parallax_error = _find_col(row, "PLX_ERROR", "PLX_ERR")
        gmag = _find_col(row, "FLUX_G", "G")

        identifiers: list[str] = []
        if ids is not None:
            identifiers = [
                item.strip() for item in str(ids).split("|") if item.strip()
            ]

        object_name = str(main_id) if main_id is not None else target
        gaia_source_id = SimbadClient.extract_gaia_source_id_from_identifiers(
            identifiers)
        parallax_mas = self._to_float(parallax)
        parallax_error_mas = self._to_float(parallax_error)
        gmag_value = self._to_float(gmag)
        distance_pc, distance_error_pc = self._distance_from_parallax(
            parallax_mas,
            parallax_error_mas,
        )
        references = self._query_references(
            target=query_name,
            object_name=object_name,
        )

        return SimbadRecord(
            object_name=object_name,
            object_type=(str(object_type).strip() if object_type is not None
                         and str(object_type).strip() else None),
            ra_deg=self._parse_ra_deg(ra),
            dec_deg=self._parse_dec_deg(dec),
            spectral_type=(str(sp_type).strip() if sp_type is not None
                           and str(sp_type).strip() else None),
            gaia_source_id=gaia_source_id,
            gaia_gmag=gmag_value,
            gaia_parallax_mas=parallax_mas,
            gaia_parallax_error_mas=parallax_error_mas,
            gaia_distance_pc=distance_pc,
            gaia_distance_error_pc=distance_error_pc,
            identifiers=identifiers,
            references=references,
        )

    @staticmethod
    def extract_gaia_source_id(record: SimbadRecord | None) -> str | None:
        if record is None:
            return None

        if record.gaia_source_id:
            return record.gaia_source_id

        return SimbadClient.extract_gaia_source_id_from_identifiers(
            record.identifiers)

    @staticmethod
    def extract_gaia_source_id_from_identifiers(
        identifiers: list[str], ) -> str | None:

        for identifier in identifiers:
            upper = identifier.upper()
            if "GAIA DR3" in upper or "GAIA DR2" in upper:
                parts = identifier.split()
                if parts:
                    return parts[-1]
        return None
