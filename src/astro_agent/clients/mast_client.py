from __future__ import annotations

import re

from astroquery.mast import Observations

from ..models import MastRecord, SimbadRecord


class MastClient:
    MISSION_COLLECTIONS = ("TESS", "K2", "Kepler", "JWST", "HST")
    TIC_PATTERN = re.compile(r"\bTIC\s*([0-9]+)\b", re.IGNORECASE)
    EPIC_PATTERN = re.compile(r"\bEPIC\s*([0-9]+)\b", re.IGNORECASE)
    KIC_PATTERN = re.compile(r"\bKIC\s*([0-9]+)\b", re.IGNORECASE)

    def __init__(self, region_radius_deg: float = 0.02) -> None:
        self._region_radius_deg = region_radius_deg

    @staticmethod
    def _extract_ids(identifiers: list[str],
                     pattern: re.Pattern[str]) -> list[str]:
        ids: set[str] = set()
        for identifier in identifiers:
            match = pattern.search(identifier)
            if match:
                ids.add(match.group(1))
        return sorted(ids, key=int)

    @staticmethod
    def _query_count_by_name(name: str,
                             obs_collection: str | None = None) -> int:
        try:
            query_criteria = getattr(Observations, "query_criteria")
            if obs_collection is None:
                table = query_criteria(target_name=name)
            else:
                table = query_criteria(
                    target_name=name,
                    obs_collection=obs_collection,
                )
            return 0 if table is None else len(table)
        except Exception:
            return 0

    @staticmethod
    def _query_count_by_region(
        ra_deg: float,
        dec_deg: float,
        obs_collection: str,
        radius_deg: float = 0.02,
    ) -> int:
        try:
            query_region = getattr(Observations, "query_region")
            coordinates = f"{ra_deg} {dec_deg}"
            table = query_region(
                coordinates,
                radius=f"{radius_deg} deg",
            )
            if table is None or len(table) == 0:
                return 0

            if "obs_collection" not in table.colnames:
                return 0

            return sum(1 for value in table["obs_collection"]
                       if str(value).upper() == obs_collection.upper())
        except Exception:
            return 0

    @staticmethod
    def _query_mission_data_by_region(
        ra_deg: float,
        dec_deg: float,
        radius_deg: float,
    ) -> tuple[dict[str, int], dict[str, str]]:
        from astropy.time import Time

        counts: dict[str, int] = {m: 0 for m in MastClient.MISSION_COLLECTIONS}
        time_info: dict[str, str] = {}

        try:
            query_region = getattr(Observations, "query_region")
            coordinates = f"{ra_deg} {dec_deg}"
            table = query_region(coordinates, radius=f"{radius_deg} deg")

            if table is None or len(
                    table) == 0 or "obs_collection" not in table.colnames:
                return counts, time_info

            has_seq = "sequence_number" in table.colnames
            has_tmin = "t_min" in table.colnames
            has_tmax = "t_max" in table.colnames

            per_mission: dict[str, dict[str, list]] = {
                m: {
                    "seq": [],
                    "t_min": [],
                    "t_max": []
                }
                for m in MastClient.MISSION_COLLECTIONS
            }

            for row in table:
                collection = str(row["obs_collection"])
                if collection not in per_mission:
                    continue
                counts[collection] += 1
                data = per_mission[collection]
                if has_seq:
                    try:
                        sn = int(row["sequence_number"])
                        if sn > 0:
                            data["seq"].append(sn)
                    except (ValueError, TypeError):
                        pass
                if has_tmin:
                    try:
                        v = float(row["t_min"])
                        if v > 0:
                            data["t_min"].append(v)
                    except (ValueError, TypeError):
                        pass
                if has_tmax:
                    try:
                        v = float(row["t_max"])
                        if v > 0:
                            data["t_max"].append(v)
                    except (ValueError, TypeError):
                        pass

            def fmt_mjd(mjd: float) -> str:
                try:
                    return str(Time(mjd, format="mjd").strftime("%Y-%m"))
                except Exception:
                    return "?"

            seq_labels = {
                "TESS": "Sector",
                "K2": "Campaign",
                "Kepler": "Quarter"
            }

            for mission, data in per_mission.items():
                if counts[mission] == 0:
                    continue
                parts: list[str] = []

                seqs = sorted(set(data["seq"]))
                if seqs and mission in seq_labels:
                    label = seq_labels[mission]
                    if len(seqs) <= 10:
                        parts.append(
                            f"{label}s {', '.join(str(s) for s in seqs)}")
                    else:
                        parts.append(
                            f"{label}s {seqs[0]}-{seqs[-1]} ({len(seqs)} total)"
                        )

                tmins = data["t_min"]
                tmaxs = data["t_max"]
                if tmins and tmaxs:
                    t_start = fmt_mjd(min(tmins))
                    t_end = fmt_mjd(max(tmaxs))
                    parts.append(t_start if t_start ==
                                 t_end else f"{t_start} ~ {t_end}")

                if parts:
                    time_info[mission] = "; ".join(parts)

            return counts, time_info

        except Exception:
            return counts, {}

    def query(self, simbad: SimbadRecord | None) -> MastRecord | None:
        if simbad is None:
            return None

        tic_ids = self._extract_ids(simbad.identifiers, self.TIC_PATTERN)
        epic_ids = self._extract_ids(simbad.identifiers, self.EPIC_PATTERN)
        kic_ids = self._extract_ids(simbad.identifiers, self.KIC_PATTERN)

        mission_observations: dict[str, int] = {
            mission: 0
            for mission in self.MISSION_COLLECTIONS
        }
        mission_time_info: dict[str, str] = {}
        if simbad.ra_deg is not None and simbad.dec_deg is not None:
            mission_observations, mission_time_info = self._query_mission_data_by_region(
                simbad.ra_deg,
                simbad.dec_deg,
                self._region_radius_deg,
            )

        jwst_observations = self._query_count_by_name(
            simbad.object_name,
            obs_collection="JWST",
        )
        hst_observations = self._query_count_by_name(
            simbad.object_name,
            obs_collection="HST",
        )

        if simbad.ra_deg is not None and simbad.dec_deg is not None:
            if jwst_observations == 0:
                jwst_observations = self._query_count_by_region(
                    simbad.ra_deg,
                    simbad.dec_deg,
                    obs_collection="JWST",
                    radius_deg=self._region_radius_deg,
                )
            if hst_observations == 0:
                hst_observations = self._query_count_by_region(
                    simbad.ra_deg,
                    simbad.dec_deg,
                    obs_collection="HST",
                    radius_deg=self._region_radius_deg,
                )

        mission_observations["JWST"] = max(
            mission_observations.get("JWST", 0),
            jwst_observations,
        )
        mission_observations["HST"] = max(
            mission_observations.get("HST", 0),
            hst_observations,
        )
        jwst_observations = mission_observations["JWST"]
        hst_observations = mission_observations["HST"]

        if not tic_ids and not epic_ids and not kic_ids and sum(
                mission_observations.values()) == 0:
            return None

        return MastRecord(
            tic_ids=tic_ids,
            epic_ids=epic_ids,
            kic_ids=kic_ids,
            mission_observations=mission_observations,
            mission_time_info=mission_time_info,
            total_mission_observations=sum(mission_observations.values()),
            region_radius_deg=self._region_radius_deg,
            jwst_observations=jwst_observations,
            hst_observations=hst_observations,
        )
