export function spectrumTooltipLabel(frequency) {
  const numericFrequency = Number(frequency);
  if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) {
    return "Frequency: -";
  }
  return `Frequency: ${numericFrequency.toPrecision(7)}  Period: ${(1 / numericFrequency).toPrecision(7)}`;
}

export function fluxTooltipFormatter(value, name, item) {
  const time = item?.payload?.time;
  const segment = item?.payload?.segment;
  const parts = [];
  if (Number.isFinite(value)) parts.push(`Flux: ${value.toPrecision(6)}`);
  if (Number.isFinite(time)) parts.push(`Time: ${time.toPrecision(10)}`);
  if (segment != null) parts.push(`Segment: ${segment}`);
  return [parts.join("  |  "), name];
}

export function periodogramTooltipFormatter(value, name, item) {
  if (name === "power" && item?.payload?.period) {
    return [`${value.toPrecision(7)}`, `power, period ${item.payload.period.toPrecision(7)}`];
  }
  return [Number(value).toPrecision(7), name];
}
