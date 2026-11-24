"""Build firms.csv from the ABN Bulk Extract.

1. Download both zip files of the "ABN Bulk Extract" dataset from data.gov.au
   (public_split_1_10.zip and public_split_11_20.zip; about 1 GB each). There
   is no need to unzip them.
2. Run:

    python build_firm_list.py ~/Downloads/public_split_1_10.zip ~/Downloads/public_split_11_20.zip

This adds every active ABN whose name looks like a law firm to firms.csv
(existing rows, and any websites already filled in, are kept). Then run
find_websites.py to fill in the website column.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lawfirm_enrich.abr import build_firm_list  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", help="ABN Bulk Extract zip files, XML files, or folders of them")
    parser.add_argument("--out", default="firms.csv", help="CSV to create or extend (default: firms.csv)")
    parser.add_argument("--dnc", default="do_not_contact.csv", help="do-not-contact CSV (default: do_not_contact.csv)")
    parser.add_argument("--state", nargs="+", default=[], help="only these states, e.g. NSW VIC (default: all)")
    parser.add_argument(
        "--include-conveyancers",
        action="store_true",
        help="also add businesses named '... Conveyancing' (most are licensed conveyancers, not law firms)",
    )
    args = parser.parse_args(argv)

    missing = [s for s in [*args.sources, args.dnc] if not Path(s).exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    res = build_firm_list(
        args.sources,
        args.out,
        args.dnc,
        states=args.state,
        include_conveyancers=args.include_conveyancers,
        source_label=f"ABN Bulk Extract (read {date.today().isoformat()})",
    )
    print(f"Records read:                  {res.records_read:,}")
    print(f"Law firm ABNs found:           {res.law_firms_found:,}")
    print(f"Firms after merging entities:  {res.after_merge:,}")
    print(f"Already in {args.out}:         {res.already_listed:,}")
    print(f"Left out (do-not-contact):     {res.dnc_excluded:,}")
    print(f"Added:                         {res.added:,}")
    print(f"Firms now in {args.out}:       {res.total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
