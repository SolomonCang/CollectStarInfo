from __future__ import annotations

from astroquery.gaia import Gaia
import astropy.units as u

from ..models import GaiaRecord, SimbadRecord
from .simbad_client import SimbadClient


class GaiaClient:

    def __init__(self, cone_radius_arcsec: float = 5.0) -> None:
        self._cone_radius_arcsec = cone_radius_arcsec

    @staticmethod
    def _distance_from_parallax(
            parallax_mas: float | None, parallax_err_mas: float | None
    ) -> tuple[float | None, float | None]:
        if parallax_mas is None or parallax_mas <= 0:
            return None, None

        distance_pc = 1000.0 / parallax_mas
        if parallax_err_mas is None:
            return distance_pc, None

        # First-order propagation: d = 1000 / p
        distance_err_pc = 1000.0 * parallax_err_mas / (parallax_mas**2)
        return distance_pc, distance_err_pc

    @staticmethod
    def _to_gaia_record(row) -> GaiaRecord:
        source_id = str(
            row["source_id"]) if "source_id" in row.colnames else None
        gmag = float(row["phot_g_mean_mag"]
                     ) if "phot_g_mean_mag" in row.colnames else None
        parallax = float(
            row["parallax"]) if "parallax" in row.colnames else None
        parallax_error = float(row["parallax_error"]
                               ) if "parallax_error" in row.colnames else None

        distance_pc, distance_err_pc = GaiaClient._distance_from_parallax(
            parallax, parallax_error)

        return GaiaRecord(
            source_id=source_id,
            gmag=gmag,
            parallax_mas=parallax,
            parallax_error_mas=parallax_error,
            distance_pc=distance_pc,
            distance_error_pc=distance_err_pc,
        )

    @staticmethod
    def from_simbad_record(simbad: SimbadRecord | None) -> GaiaRecord | None:
        if simbad is None:
            return None

        source_id = SimbadClient.extract_gaia_source_id(simbad)
        gmag = simbad.gaia_gmag
        parallax = simbad.gaia_parallax_mas
        parallax_error = simbad.gaia_parallax_error_mas

        if source_id is None and gmag is None and parallax is None and parallax_error is None:
            return None

        distance_pc = simbad.gaia_distance_pc
        distance_error_pc = simbad.gaia_distance_error_pc
        if distance_pc is None and parallax is not None:
            distance_pc, distance_error_pc = GaiaClient._distance_from_parallax(
                parallax,
                parallax_error,
            )

        return GaiaRecord(
            source_id=source_id,
            gmag=gmag,
            parallax_mas=parallax,
            parallax_error_mas=parallax_error,
            distance_pc=distance_pc,
            distance_error_pc=distance_error_pc,
        )

    @staticmethod
    def is_complete(record: GaiaRecord | None) -> bool:
        if record is None:
            return False

        return all(value is not None for value in (
            record.source_id,
            record.gmag,
            record.parallax_mas,
            record.parallax_error_mas,
            record.distance_pc,
            record.distance_error_pc,
        ))

    @staticmethod
    def merge_records(primary: GaiaRecord,
                      fallback: GaiaRecord | None) -> GaiaRecord:
        if fallback is None:
            return primary

        return GaiaRecord(
            source_id=primary.source_id or fallback.source_id,
            gmag=primary.gmag if primary.gmag is not None else fallback.gmag,
            parallax_mas=(primary.parallax_mas if primary.parallax_mas
                          is not None else fallback.parallax_mas),
            parallax_error_mas=(primary.parallax_error_mas
                                if primary.parallax_error_mas is not None else
                                fallback.parallax_error_mas),
            distance_pc=(primary.distance_pc if primary.distance_pc is not None
                         else fallback.distance_pc),
            distance_error_pc=(primary.distance_error_pc
                               if primary.distance_error_pc is not None else
                               fallback.distance_error_pc),
        )

    def query_with_simbad_priority(
            self, simbad: SimbadRecord | None) -> GaiaRecord | None:
        primary = self.from_simbad_record(simbad)
        if self.is_complete(primary):
            return primary

        source_id = SimbadClient.extract_gaia_source_id(simbad)
        fallback = self.query(source_id, simbad)
        if primary is None:
            return fallback
        return self.merge_records(primary, fallback)

    def query_by_source_id(self, source_id: str) -> GaiaRecord | None:
        query = f"""
            SELECT source_id, phot_g_mean_mag, parallax, parallax_error
            FROM gaiadr3.gaia_source
            WHERE source_id = {source_id}
        """
        job = Gaia.launch_job(query)
        table = job.get_results()
        if table is None or len(table) == 0:
            return None
        return self._to_gaia_record(table[0])

    def query_by_position(
        self,
        ra_deg: float,
        dec_deg: float,
        radius_arcsec: float | None = None,
    ) -> GaiaRecord | None:
        radius_value = self._cone_radius_arcsec if radius_arcsec is None else radius_arcsec
        radius = u.Quantity(radius_value, u.Unit("arcsec"))
        query = f"""
            SELECT TOP 1 source_id, phot_g_mean_mag, parallax, parallax_error,
                   DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {ra_deg}, {dec_deg})) AS dist
            FROM gaiadr3.gaia_source
            WHERE 1 = CONTAINS(
                POINT('ICRS', ra, dec),
                CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius.to(u.Unit("deg")).value})
            )
            ORDER BY dist ASC
        """
        job = Gaia.launch_job(query)
        table = job.get_results()
        if table is None or len(table) == 0:
            return None
        return self._to_gaia_record(table[0])

    def query(self, source_id: str | None,
              simbad: SimbadRecord | None) -> GaiaRecord | None:
        if source_id:
            result = self.query_by_source_id(source_id)
            if result is not None:
                return result

        if simbad and simbad.ra_deg is not None and simbad.dec_deg is not None:
            return self.query_by_position(simbad.ra_deg, simbad.dec_deg)

        return None
