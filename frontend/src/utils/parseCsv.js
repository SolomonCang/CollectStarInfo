export function parseCsv(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split(/,|\s+/).map(Number))
    .filter((columns) => Number.isFinite(columns[0]) && Number.isFinite(columns[1]))
    .map(([time, flux, flux_error]) => ({
      time,
      flux,
      flux_error: Number.isFinite(flux_error) ? flux_error : null,
    }));
}
