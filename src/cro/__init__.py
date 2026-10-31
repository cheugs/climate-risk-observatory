"""Climate Risk & Human Development Observatory.

A small, reproducible research pipeline that:
1. downloads climate, population and development data,
2. stores it in PostGIS (or Parquet if the database is not running),
3. builds hazard / exposure / vulnerability indicators,
4. runs the statistical tests described in the report,
5. exports maps and a dashboard.
"""

__version__ = "0.1.0"
