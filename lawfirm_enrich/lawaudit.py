"""LawAudit firm data: one command for every step.

    python lawaudit.py status                       where things stand, and the next step
    python lawaudit.py build-list ZIP1 ZIP2         build firms.csv from the ABN Bulk Extract
    python lawaudit.py find-websites [--limit 50]   fill in firms' websites
    python lawaudit.py crawl                        crawl the websites, update the master list
    python lawaudit.py make-list [options]          export a postal or email list
    python lawaudit.py unsubscribe FILE_OR_EMAIL    record unsubscribes (add --whole-firm to drop the firm)

Add --help after any step for its options, e.g.  python lawaudit.py make-list --help
Run it from the lawfirm_enrich folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _status(argv: list[str]) -> int:
    from lawfirm_enrich.status import status_report

    parser = argparse.ArgumentParser(prog="lawaudit.py status", description="Show where things stand.")
    parser.add_argument("--firms", default="firms.csv")
    parser.add_argument("--master", default="data/master.xlsx")
    parser.add_argument("--dnc", default="do_not_contact.csv")
    parser.add_argument("--unsubscribed", default="unsubscribed.csv")
    args = parser.parse_args(argv)
    print(status_report(args.firms, args.master, args.dnc, args.unsubscribed))
    return 0


def _unsubscribe(argv: list[str]) -> int:
    from lawfirm_enrich.inputs import ensure_default_dnc
    from lawfirm_enrich.master import check_writable
    from lawfirm_enrich.unsubscribe import process_unsubscribes

    parser = argparse.ArgumentParser(
        prog="lawaudit.py unsubscribe",
        description="Record unsubscribed email addresses: files exported from your email service (any CSV or "
        "text file; addresses are picked out automatically) and/or addresses typed directly.",
    )
    parser.add_argument("sources", nargs="+", help="files and/or email addresses")
    parser.add_argument(
        "--whole-firm",
        action="store_true",
        help="also put each address's firm on do_not_contact.csv and remove it from the master list",
    )
    parser.add_argument("--master", default="data/master.xlsx")
    parser.add_argument("--dnc", default="do_not_contact.csv")
    parser.add_argument("--unsubscribed", default="unsubscribed.csv")
    args = parser.parse_args(argv)
    try:
        check_writable(args.master)
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    ensure_default_dnc(args.dnc)
    if not Path(args.dnc).exists():
        print(f"error: do-not-contact file not found: {args.dnc}", file=sys.stderr)
        return 2
    label = ", ".join(Path(s).name if Path(s).is_file() else "typed" for s in args.sources)
    res = process_unsubscribes(
        args.sources, args.unsubscribed, args.master, args.dnc, whole_firm=args.whole_firm, source_label=label
    )
    if not res.addresses:
        print("No email addresses found in what you gave.", file=sys.stderr)
        return 1
    print(f"Addresses read:                 {len(res.addresses)}")
    print(f"Newly added to {args.unsubscribed}: {res.newly_added}")
    print(f"Removed from the master list:   {res.found_in_master}")
    if res.firms_added_to_dnc:
        print(f"Firms put on do-not-contact:    {', '.join(res.firms_added_to_dnc)}")
    return 0


def _script(module: str, step: str):
    def run(argv: list[str]) -> int:
        sys.argv[0] = f"lawaudit.py {step}"  # so the step's --help shows how to call it
        return __import__(module).main(argv)

    return run


COMMANDS = {
    "status": _status,
    "build-list": _script("build_firm_list", "build-list"),
    "find-websites": _script("find_websites", "find-websites"),
    "crawl": _script("run", "crawl"),
    "make-list": _script("make_list", "make-list"),
    "unsubscribe": _unsubscribe,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    command = COMMANDS.get(argv[0])
    if command is None:
        print(f"Unknown step '{argv[0]}'. Steps: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return command(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
