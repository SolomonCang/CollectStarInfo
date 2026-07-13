/**
 * Fold a light curve to phase [0, 2] (dual-cycle) for a given period.
 * @param {Array<{time:number, normalized_flux:number}>} curve
 * @param {number} period
 * @returns {Array<{phase:number, flux:number, time:number}>}
 */
export function foldCurve(curve, period) {
  if (!Number.isFinite(period) || period <= 0) {
    return [];
  }
  const singleCycle = curve
    .map((point) => ({
      phase: ((point.time / period) % 1 + 1) % 1,
      flux: point.normalized_flux,
      time: point.time,
    }))
    .filter((point) => Number.isFinite(point.phase) && Number.isFinite(point.flux))
    .sort((left, right) => left.phase - right.phase);
  const dualCycle = [
    ...singleCycle,
    ...singleCycle.map((point) => ({ ...point, phase: point.phase + 1 })),
  ];
  return dualCycle;
}

/**
 * Bin-fold a light curve into numBins phase bins, dual-cycle [0, 2].
 */
export function foldCurveBinned(curve, period, numBins = 20) {
  if (!Number.isFinite(period) || period <= 0 || !curve.length) {
    return [];
  }
  const bins = Array.from({ length: numBins }, (_, i) => ({
    phase: (i + 0.5) / numBins,
    sum: 0,
    sumSq: 0,
    count: 0,
  }));
  for (const point of curve) {
    const phase = ((point.time / period) % 1 + 1) % 1;
    if (!Number.isFinite(phase) || !Number.isFinite(point.normalized_flux)) continue;
    const idx = Math.min(numBins - 1, Math.floor(phase * numBins));
    bins[idx].sum += point.normalized_flux;
    bins[idx].sumSq += point.normalized_flux * point.normalized_flux;
    bins[idx].count += 1;
  }
  const singleBin = bins
    .filter((bin) => bin.count > 0)
    .map((bin) => ({
      phase: bin.phase,
      flux: bin.sum / bin.count,
      std: bin.count > 1 ? Math.sqrt((bin.sumSq - (bin.sum * bin.sum) / bin.count) / (bin.count - 1)) : 0,
    }));
  return [
    ...singleBin,
    ...singleBin.map((bin) => ({ phase: bin.phase + 1, flux: bin.flux, std: bin.std })),
  ];
}

/**
 * Downsample curve for large datasets to avoid SVG performance issues.
 * Uses a simple stride-based approach for scatter plots.
 */
export function downsampleCurve(curve, maxPoints = 5000) {
  if (curve.length <= maxPoints) return curve;
  const step = Math.ceil(curve.length / maxPoints);
  return curve.filter((_, i) => i % step === 0);
}

/**
 * Compute standard deviation for error bars on binned data.
 */
export function binWithErrors(curve, period, numBins = 20) {
  if (!Number.isFinite(period) || period <= 0 || !curve.length) {
    return [];
  }
  const bins = Array.from({ length: numBins }, (_, i) => ({
    phase: (i + 0.5) / numBins,
    sum: 0,
    sumSq: 0,
    count: 0,
  }));
  for (const point of curve) {
    const phase = ((point.time / period) % 1 + 1) % 1;
    if (!Number.isFinite(phase) || !Number.isFinite(point.normalized_flux)) continue;
    const idx = Math.min(numBins - 1, Math.floor(phase * numBins));
    const val = point.normalized_flux;
    bins[idx].sum += val;
    bins[idx].sumSq += val * val;
    bins[idx].count += 1;
  }
  return bins
    .filter((bin) => bin.count > 0)
    .map((bin) => ({
      phase: bin.phase,
      flux: bin.sum / bin.count,
      std: bin.count > 1 ? Math.sqrt((bin.sumSq - (bin.sum * bin.sum) / bin.count) / (bin.count - 1)) : 0,
    }));
}
