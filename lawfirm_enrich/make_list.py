"""Export a mailing list from the master list.

    python make_list.py --size Sole "Small (2-4)" --state NSW VIC --area conveyancing wills_estates \
        --not-contacted-days 180 --out output/mailing_list.csv --mark-contacted
    python make_list.py --channel email --general-email-only --out output/email_list.csv

Firms classified Exclude and firms on do_not_contact.csv are never included. The
email channel also never includes a firm whose site says it does not accept
unsolicited email.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lawfirm_enrich.lists import AREAS, SIZES, Criteria, make_list  # noqa: E402
from lawfirm_enrich.master import check_writable  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--master", default="data/master.xlsx", help="master list (default: data/master.xlsx)")
    parser.add_argument("--dnc", default="do_not_contact.csv", help="do-not-contact CSV")
    parser.add_argument("--out", default="output/mailing_list.csv", help="CSV to write")
    parser.add_argument(
        "--size",
        nargs="+",
        choices=SIZES,
        default=["Sole", "Small (2-4)", "Larger"],
        help="classifications to include (default: Sole, Small (2-4), Larger)",
    )
    parser.add_argument("--state", nargs="+", default=[], help="states to include, e.g. NSW VIC (default: all)")
    parser.add_argument(
        "--area",
        nargs="+",
        choices=AREAS,
        default=[],
        help="include firms doing at least one of these practice areas (default: any)",
    )
    parser.add_argument(
        "--not-contacted-days",
        type=int,
        default=0,
        help="leave out firms whose last_contacted is within this many days",
    )
    parser.add_argument(
        "--channel",
        choices=("post", "email"),
        default="post",
        help="post: firms with a postal address (default); email: firms with a published email address "
        "and no 'no unsolicited email' notice on their site",
    )
    parser.add_argument(
        "--general-email-only",
        action="store_true",
        help="email channel: only general addresses such as info@, not individuals' addresses",
    )
    parser.add_argument(
        "--include-no-address", action="store_true", help="post channel: include firms with no postal address found"
    )
    parser.add_argument(
        "--mark-contacted",
        action="store_true",
        help="set last_contacted to today in the master list for every firm exported",
    )
    args = parser.parse_args(argv)

    for label, path in (("master list", args.master), ("do-not-contact", args.dnc)):
        if not Path(path).exists():
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 2
    try:
        check_writable(args.master)
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    criteria = Criteria(
        sizes=args.size,
        states=args.state,
        areas=args.area,
        not_contacted_days=args.not_contacted_days,
        channel=args.channel,
        require_address=not args.include_no_address,
        general_email_only=args.general_email_only,
    )
    n = make_list(args.master, args.dnc, args.out, criteria, mark_contacted=args.mark_contacted)
    print(f"Wrote {n} firms to {args.out}" + (" and marked them contacted today" if args.mark_contacted and n else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
