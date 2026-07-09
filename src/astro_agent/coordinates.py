from __future__ import annotations

from dataclasses import dataclass
import re

from astropy.coordinates import SkyCoord
import astropy.units as u

_DECIMAL_TOKEN_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class ParsedCoordinateInput:
    raw_input: str
    normalized_input: str
    skycoord: SkyCoord
    format_name: str


def _normalize_coordinate_text(value: str) -> str:
    text = value.strip()
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _parse_decimal_degrees(text: str) -> SkyCoord | None:
    decimal_text = text.replace(",", " ")
    tokens = [token for token in decimal_text.split() if token]
    if len(tokens) != 2:
        return None
    if not all(_DECIMAL_TOKEN_PATTERN.match(token) for token in tokens):
        return None

    ra_deg = float(tokens[0])
    dec_deg = float(tokens[1])
    if not 0.0 <= ra_deg < 360.0:
        return None
    if not -90.0 <= dec_deg <= 90.0:
        return None

    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")


def _parse_sexagesimal(text: str) -> SkyCoord | None:
    sexagesimal_text = text.replace(",", " ")
    if any(marker in sexagesimal_text.lower()
           for marker in ("h", "m", "s", "d")) or ":" in sexagesimal_text:
        try:
            return SkyCoord(sexagesimal_text,
                            unit=(u.hourangle, u.deg),
                            frame="icrs")
        except Exception:
            return None

    tokens = [token for token in sexagesimal_text.split() if token]
    if len(tokens) not in {4, 6}:
        return None
    if not all(_DECIMAL_TOKEN_PATTERN.match(token) for token in tokens):
        return None

    midpoint = len(tokens) // 2
    ra_text = " ".join(tokens[:midpoint])
    dec_text = " ".join(tokens[midpoint:])
    try:
        return SkyCoord(ra_text,
                        dec_text,
                        unit=(u.hourangle, u.deg),
                        frame="icrs")
    except Exception:
        return None


def parse_coordinate_input(value: str) -> ParsedCoordinateInput | None:
    normalized = _normalize_coordinate_text(value)
    if not normalized:
        return None

    decimal_coord = _parse_decimal_degrees(normalized)
    if decimal_coord is not None:
        return ParsedCoordinateInput(
            raw_input=value,
            normalized_input=normalized,
            skycoord=decimal_coord,
            format_name="decimal_degrees",
        )

    sexagesimal_coord = _parse_sexagesimal(normalized)
    if sexagesimal_coord is not None:
        return ParsedCoordinateInput(
            raw_input=value,
            normalized_input=normalized,
            skycoord=sexagesimal_coord,
            format_name="sexagesimal",
        )

    return None
