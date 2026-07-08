from __future__ import annotations

from typing import Any

from astropy.timeseries import LombScargle
import numpy as np

from ..schemas import LightCurveAnalysisRequest

MAX_PERIODOGRAM_POINTS = 2000
MAX_PERIODOGRAM_PEAKS = 100


def _finite_arrays(
    request: LightCurveAnalysisRequest
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    time = np.array([point.time for point in request.points], dtype=float)
    flux = np.array([point.flux for point in request.points], dtype=float)
    errors = np.array(
        [
            np.nan if point.flux_error is None else point.flux_error
            for point in request.points
        ],
        dtype=float,
    )

    mask = np.isfinite(time) & np.isfinite(flux)
    if np.isfinite(errors).any():
        errors = np.where(np.isfinite(errors), errors,
                          np.nanmedian(errors[np.isfinite(errors)]))
        mask = mask & np.isfinite(errors) & (errors > 0)
        clean_errors: np.ndarray | None = errors[mask]
    else:
        clean_errors = None

    clean_time = time[mask]
    clean_flux = flux[mask]
    order = np.argsort(clean_time)
    if clean_errors is None:
        return clean_time[order], clean_flux[order], None
    return clean_time[order], clean_flux[order], clean_errors[order]


def _segment_indices(time: np.ndarray,
                     gap_threshold: float) -> list[tuple[int, int]]:
    """Find contiguous segments separated by gaps larger than *gap_threshold*.

    Returns a list of ``(start, end_exclusive)`` slice indices.
    """
    if gap_threshold is None or gap_threshold <= 0 or len(time) < 2:
        return [(0, len(time))]

    gaps = np.diff(time) > gap_threshold
    boundaries = np.where(gaps)[0] + 1
    if len(boundaries) == 0:
        return [(0, len(time))]

    segments: list[tuple[int, int]] = []
    start = 0
    for boundary in boundaries:
        segments.append((int(start), int(boundary)))
        start = boundary
    segments.append((int(start), len(time)))
    return segments


def _detrend_segment(segment_time: np.ndarray, segment_flux: np.ndarray,
                     order: int) -> tuple[np.ndarray, list[float]]:
    """Apply polynomial detrend to a single contiguous segment."""
    centered = segment_time - np.nanmedian(segment_time)
    coefficients = np.polyfit(centered, segment_flux, deg=order)
    trend = np.polyval(coefficients, centered)
    detrended = segment_flux - trend + np.nanmedian(trend)
    return detrended, coefficients.tolist()


def _detrend(time: np.ndarray, flux: np.ndarray, method: str, order: int,
             gap_threshold: float | None) -> tuple[np.ndarray,
                                                   list[float] | None]:
    if method == "none" or order == 0 or len(time) <= order:
        return flux.copy(), None

    segments = _segment_indices(time, gap_threshold or 0.0)
    segment_coefficients: list[list[float]] = []
    result = flux.copy()

    for seg_start, seg_end in segments:
        seg_len = seg_end - seg_start
        if seg_len <= order:
            # Too few points in segment – keep original flux values
            continue
        seg_time = time[seg_start:seg_end]
        seg_flux = flux[seg_start:seg_end]
        det_seg, coeffs = _detrend_segment(seg_time, seg_flux, order)
        result[seg_start:seg_end] = det_seg
        segment_coefficients.append(coeffs)

    if not segment_coefficients:
        return flux.copy(), None

    # Flatten: return coefficients only when there is a single segment;
    # otherwise return per-segment coefficients nested.
    if len(segment_coefficients) == 1:
        return result, segment_coefficients[0]

    return result, {
        "segments": len(segments),
        "per_segment_coefficients": segment_coefficients,
        "segment_count": len(segment_coefficients),
    }


def _period_bounds(time: np.ndarray, min_period: float | None,
                   max_period: float | None) -> tuple[float, float]:
    baseline = float(np.nanmax(time) - np.nanmin(time))
    cadence = np.nanmedian(np.diff(np.unique(time))) if len(
        np.unique(time)) > 1 else baseline / 20
    lower = min_period or max(float(cadence) * 2.0, baseline / 500.0)
    upper = max_period or max(baseline * 0.8, lower * 2.0)
    if upper <= lower:
        upper = lower * 2.0
    return lower, upper


def _search_period(
    time: np.ndarray,
    flux: np.ndarray,
    errors: np.ndarray | None,
    min_period: float | None,
    max_period: float | None,
    samples_per_peak: int,
) -> dict[str, Any] | None:
    if len(time) < 5 or np.nanmax(time) <= np.nanmin(time):
        return None

    lower, upper = _period_bounds(time, min_period, max_period)
    minimum_frequency = 1.0 / upper
    maximum_frequency = 1.0 / lower
    model = LombScargle(time, flux, dy=errors)
    frequency, power = model.autopower(
        minimum_frequency=minimum_frequency,
        maximum_frequency=maximum_frequency,
        samples_per_peak=samples_per_peak,
    )
    if len(power) == 0:
        return None

    best_index = int(np.nanargmax(power))
    best_frequency = float(frequency[best_index])
    best_period = 1.0 / best_frequency
    best_power = float(power[best_index])
    false_alarm = float(model.false_alarm_probability(best_power))
    phase = np.mod(time / best_period, 1.0)
    phase_order = np.argsort(phase)
    period = 1.0 / frequency

    if len(period) > MAX_PERIODOGRAM_POINTS:
        base_count = max(1, MAX_PERIODOGRAM_POINTS - MAX_PERIODOGRAM_PEAKS)
        base_indices = np.linspace(0, len(period) - 1, base_count, dtype=int)
        peak_count = min(MAX_PERIODOGRAM_PEAKS, len(period))
        peak_indices = np.argpartition(power, -peak_count)[-peak_count:]
        spectrum_indices = np.unique(
            np.concatenate([base_indices, peak_indices]))
    else:
        spectrum_indices = np.arange(len(period))
    spectrum_indices = spectrum_indices[np.argsort(frequency[spectrum_indices])]

    return {
        "best_period":
        best_period,
        "best_frequency":
        best_frequency,
        "power":
        best_power,
        "false_alarm_probability":
        false_alarm,
        "search_window": {
            "min_period": lower,
            "max_period": upper
        },
        "periodogram": [{
            "period": float(period[index]),
            "frequency": float(frequency[index]),
            "power": float(power[index]),
        } for index in spectrum_indices],
        "phase_curve": [{
            "phase": float(phase[index]),
            "flux": float(flux[index]),
            "time": float(time[index])
        } for index in phase_order],
    }


def analyze_light_curve(request: LightCurveAnalysisRequest) -> dict[str, Any]:
    time, flux, errors = _finite_arrays(request)
    if len(time) < 3:
        raise ValueError(
            "At least three finite light-curve points are required")

    detrend_method = request.detrend.method if request.detrend.enabled else "none"
    working_flux, coefficients = _detrend(
        time,
        flux,
        method=detrend_method,
        order=request.detrend.polynomial_order,
        gap_threshold=request.detrend.gap_threshold,
    )
    median_flux = float(np.nanmedian(working_flux))
    normalized_flux = working_flux / median_flux if median_flux else working_flux

    period_result = None
    if request.period_search.enabled:
        period_result = _search_period(
            time,
            normalized_flux,
            errors,
            request.period_search.min_period,
            request.period_search.max_period,
            request.period_search.samples_per_peak,
        )

    segments_info = _segment_indices(time,
                                      request.detrend.gap_threshold or 0.0)

    return {
        "point_count": int(len(time)),
        "time_span": float(np.nanmax(time) - np.nanmin(time)),
        "flux_stats": {
            "raw_median": float(np.nanmedian(flux)),
            "raw_std": float(np.nanstd(flux)),
            "normalized_median": float(np.nanmedian(normalized_flux)),
            "normalized_std": float(np.nanstd(normalized_flux)),
        },
        "detrend": {
            "method":
            detrend_method,
            "polynomial_order":
            request.detrend.polynomial_order,
            "gap_threshold":
            request.detrend.gap_threshold,
            "segment_count":
            len(segments_info),
            "polynomial_coefficients":
            coefficients,
            "curve": [{
                "time": float(time[index]),
                "raw_flux": float(flux[index]),
                "normalized_flux": float(normalized_flux[index]),
            } for index in range(len(time))],
        },
        "period_search": period_result,
    }
