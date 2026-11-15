"""Device management, run on the server (inside the container). Easiest from your laptop: ./devices

    python manage.py list
    python manage.py add-device baba-phone [--base https://docs.example.com] [--hours 48] [--qr]
    python manage.py remove-device baba-phone
    python manage.py remove-all [--yes]

add-device prints a one-time link (and, with --qr, a QR code to scan from the screen).
Open it on that device in the browser he will use, then tap "Add this device".
"""
import argparse
import sys
import time

from app import guard

ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("add-device")
a.add_argument("name")
a.add_argument("--base", default="http://localhost:8765")
a.add_argument("--hours", type=int, default=48)
a.add_argument("--qr", action="store_true", help="also print a QR code of the link")
sub.add_parser("list")
r = sub.add_parser("remove-device")
r.add_argument("name")
ra = sub.add_parser("remove-all")
ra.add_argument("--yes", action="store_true", help="don't ask for confirmation")
args = ap.parse_args()


def fmt(t, f="%Y-%m-%d %H:%M"):
    return time.strftime(f, time.localtime(t))


if args.cmd == "add-device":
    code = guard.new_enroll_code(args.name, args.hours)
    link = f"{args.base.rstrip('/')}/enroll/{code}"
    print(f"\n  {args.name}: {link}\n  (one-time, valid {args.hours} h)\n")
    if args.qr:
        import segno

        segno.make(link, error="m").terminal(compact=True)
elif args.cmd == "remove-device":
    n = guard.remove_device(args.name)
    print(f"removed {args.name}" if n else f"no device or link named {args.name!r}")
elif args.cmd == "remove-all":
    d = guard.list_devices()
    names = sorted({x["name"] for x in d["devices"] + d["enroll"]})
    if not names:
        print("nothing to remove")
        sys.exit()
    if not args.yes:
        ans = input(f"Remove ALL {len(names)} ({', '.join(names)})? They will need new links. Type yes: ")
        if ans.strip().lower() != "yes":
            sys.exit("cancelled")
    for n in names:
        guard.remove_device(n)
    print(f"removed: {', '.join(names)}")
else:
    d = guard.list_devices()
    if not d["devices"] and not d["enroll"]:
        print("no devices yet")
    for x in d["devices"]:
        print(f"  active   {x['name']:18} added   {fmt(x['created'], '%Y-%m-%d')}")
    for x in d["enroll"]:
        print(f"  link     {x['name']:18} unused, expires {fmt(x['expires'])}")
