# Parameter Extraction Reference

## Core Parameters And Search Cues

### Period

Likely phrases:
- rotation period
- photometric period
- modulation period
- Prot
- rotational modulation

Common confusion:
- orbital period
- pulsation period
- frequency spacing

Typical sources:
- light-curve analysis sections
- variability tables
- rotation catalogs

### Mass

Likely phrases:
- mass
- masses
- stellar mass
- dynamical mass
- evolutionary mass
- seismic mass

Common confusion:
- mass ratio only
- minimum mass only

Typical sources:
- orbital solution tables
- spectroscopy plus evolutionary-model sections
- asteroseismic modeling tables

### Teff

Likely phrases:
- effective temperature
- Teff
- T_eff

Common confusion:
- catalog temperature versus spectroscopic temperature

Typical sources:
- atmospheric parameter tables
- spectral fitting sections
- survey catalogs such as LAMOST-derived tables

### log g

Likely phrases:
- log g
- logg
- surface gravity

Common confusion:
- catalog estimate versus refined spectroscopic solution

Typical sources:
- stellar parameter tables
- spectroscopy pipelines and appendices

### vsini

Likely phrases:
- v sin i
- vsini
- projected rotational velocity

Common confusion:
- equatorial rotation velocity inferred from radius and period

Typical sources:
- line broadening analysis
- spectroscopy tables

### RV

Likely phrases:
- radial velocity
- RV
- systemic velocity
- gamma velocity

Common confusion:
- individual epoch RVs versus center-of-mass velocity

Typical sources:
- orbital solution tables
- survey spectroscopy tables

### INCL

Likely phrases:
- inclination
- orbital inclination
- spin inclination
- i

Common confusion:
- orbital inclination versus stellar rotation-axis inclination

Typical sources:
- binary-orbit modeling
- light-curve modeling
- interferometry or seismic inference

### <Bl>

Likely phrases:
- mean longitudinal magnetic field
- longitudinal magnetic field
- <Bl>
- B_l
- Bz

Common confusion:
- polar field strength
- field modulus

Typical sources:
- spectropolarimetry sections
- magnetic measurements tables

## Prioritization Heuristics

- Spectroscopic binary papers are strong candidates for RV, mass, INCL, Teff, log g, and vsini.
- Asteroseismology papers are strong candidates for period, inclination, and occasionally mass.
- Magnetic-star papers are the main candidates for <Bl>.
- Survey recalibration papers may contain Teff, log g, RV, and vsini, but often only as catalog entries.

## Extraction Rules

- Preserve uncertainties and units exactly as published.
- Preserve component labels such as primary, secondary, Aa, Ab, or system.
- When multiple values exist, keep each with method and bibcode.
- Prefer peer-reviewed values over unverified catalog mirrors unless the catalog is the primary published source.

## Escalation Triggers

Build or extend a script when:
- a target has many references and manual ranking is slow
- the same parameter search is repeated across many result JSON files
- you need consistent query strings and paper ranking across a batch