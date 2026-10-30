"""Command line interface.

Everything is run through one command, `cro`, so the order of the steps is
written down in one place instead of being hidden in notebooks.

Examples:
    cro boundaries        # download region polygons
    cro climate-points    # choose climate sample points
    cro population        # population per region and per point
    cro climate           # download climate data and build indicators
    cro development       # World Bank + Global Data Lab data
    cro build             # build hazard, exposure and risk indices
    cro load              # copy everything into PostGIS
    cro analyze           # run the statistics
    cro export            # save figures and maps
    cro all               # run every step in the right order
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cro", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=[
        "boundaries", "climate-points", "population", "climate", "development",
        "build", "load", "analyze", "export", "report", "app", "all",
        "probe", "validate",
    ])
    parser.add_argument("--iso3", nargs="*", default=None,
                        help="Countries to use, e.g. FRA USA IND (default: config pilot list)")
    args = parser.parse_args(argv)

    command = args.command

    # Imports happen inside each branch so that, for example, the dashboard
    # can run without the ingestion libraries being importable.
    if command == "boundaries":
        from cro.ingest import boundaries
        boundaries.run(args.iso3)

    elif command == "climate-points":
        from cro.ingest import climate
        climate.build_points()

    elif command == "population":
        from cro.ingest import population
        population.run()

    elif command == "climate":
        from cro.ingest import climate
        climate.run()

    elif command == "development":
        from cro.ingest import development
        development.run()

    elif command == "build":
        from cro.features import build
        build.run()

    elif command == "load":
        from cro.db import load
        load.run()

    elif command == "analyze":
        from cro.analysis import run_all
        run_all.run()

    elif command == "export":
        from cro.viz import export
        export.run()

    elif command == "report":
        from cro.report import build_report
        build_report.run()

    elif command == "app":
        from cro.app.app import run_app
        run_app()

    elif command == "probe":
        from cro.ingest import probes
        probes.run()

    elif command == "validate":
        from cro import validate
        validate.run()

    elif command == "all":
        from cro.ingest import boundaries, climate, development, population
        boundaries.run(args.iso3)
        climate.build_points()
        population.run()
        climate.run()
        development.run()

        from cro.features import build
        build.run()

        from cro.analysis import run_all
        run_all.run()

        from cro.viz import export
        export.run()

        print("\nPipeline finished. Start the dashboard with: cro app")


if __name__ == "__main__":
    main()
