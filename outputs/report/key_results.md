# Key results

- Regions analysed: **105** in **3** countries.
- Population covered: **1803.1 million**.
- Regions with development data: **99**.

## H1 - exposure is concentrated
- The top 10% most hazardous regions hold **1.38x** their population share of person-days of extreme heat (95% CI 1.21 to 1.75).

## H2 - high hazard goes with lower development
- Median SHDI in high-hazard regions: **0.786**.
- Median SHDI in low-hazard regions: **0.936**.
- Mann-Whitney p = **1.44e-06**, Cliff's delta = **-0.56**.

## H3 - does it survive country fixed effects?
- A one standard deviation increase in hazard is associated with **-0.21** standard deviations of SHDI (95% CI -0.32 to -0.11, p = 0, N = 99) within countries.

## H4 - spatial clustering
- Moran's I for `FRA:hazard_equal`: **0.55**.
- Moran's I for `FRA:shdi`: **-0.31**.
- Moran's I for `FRA:exposure_score`: **0.51**.
- Moran's I for `FRA:risk_equal`: **0.59**.
- Moran's I for `IND:hazard_equal`: **0.47**.
- Moran's I for `IND:shdi`: **0.38**.
- Moran's I for `IND:exposure_score`: **0.20**.
- Moran's I for `IND:risk_equal`: **0.25**.
- Moran's I for `USA:hazard_equal`: **0.69**.
- Moran's I for `USA:shdi`: **0.55**.
- Moran's I for `USA:exposure_score`: **0.61**.
- Moran's I for `USA:risk_equal`: **0.72**.

## Highest-risk regions

1. Bihār (India) - risk 0.825
1. Uttar Pradesh (India) - risk 0.815
1. Gujarāt (India) - risk 0.788
1. Madhya Pradesh (India) - risk 0.770
1. Jhārkhand (India) - risk 0.705
1. Odisha (India) - risk 0.696
1. Andhra Pradesh (India) - risk 0.692
1. Mahārāshtra (India) - risk 0.667
1. Chhattīsgarh (India) - risk 0.649
1. West Bengal (India) - risk 0.648

> These are associations, not causal effects. See the limitations section.