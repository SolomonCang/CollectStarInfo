import test from "node:test";
import assert from "node:assert/strict";
import { parseCsv } from "../src/utils/parseCsv.js";
import {
  downsampleCurve,
  foldCurve,
  foldCurveBinned,
} from "../src/utils/foldCurve.js";

test("parseCsv accepts comma and whitespace separated rows", () => {
  const points = parseCsv([
    "time,flux,flux_error",
    "0,1.0,0.1",
    "1 0.9 0.2",
    "invalid,row",
    "2,1.1",
  ].join("\n"));

  assert.deepEqual(points, [
    { time: 0, flux: 1, flux_error: 0.1 },
    { time: 1, flux: 0.9, flux_error: 0.2 },
    { time: 2, flux: 1.1, flux_error: null },
  ]);
});

test("foldCurve returns two sorted phase cycles", () => {
  const folded = foldCurve([
    { time: 0, normalized_flux: 1 },
    { time: 1, normalized_flux: 0.9 },
    { time: 2, normalized_flux: 1.1 },
  ], 2);

  assert.deepEqual(
    folded.map((point) => point.phase),
    [0, 0, 0.5, 1, 1, 1.5]
  );
  assert.deepEqual(foldCurve([], 0), []);
});

test("foldCurveBinned computes values and duplicates the cycle", () => {
  const binned = foldCurveBinned([
    { time: 0, normalized_flux: 1 },
    { time: 0.1, normalized_flux: 3 },
    { time: 0.6, normalized_flux: 2 },
  ], 1, 2);

  assert.equal(binned.length, 4);
  assert.equal(binned[0].flux, 2);
  assert.equal(binned[0].std, Math.SQRT2);
  assert.equal(binned[2].phase, binned[0].phase + 1);
});

test("downsampleCurve keeps input size under the requested limit", () => {
  const curve = Array.from({ length: 10 }, (_, index) => ({ index }));
  const sampled = downsampleCurve(curve, 4);

  assert.deepEqual(sampled.map((point) => point.index), [0, 3, 6, 9]);
  assert.equal(downsampleCurve(curve, 20), curve);
});
