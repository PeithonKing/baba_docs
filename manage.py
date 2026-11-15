"""Device management, run on the server (or with the same data/ folder):

    .venv/bin/python manage.py add-device baba-phone [--base https://docs.example.com]
    .venv/bin/python manage.py list
    .venv/bin/python manage.py remove-device baba-phone

add-device prints a one-time link (valid 48 h). Open it on that device, in Chrome,
before installing the app to the home screen.
"""
import argparse
import time

from app import guard

ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("add-device")
a.add_argument("name")
a.add_argument("--base", default="http://localhost:8765")
a.add_argument("--hours", type=int, default=48)
sub.add_parser("list")
r = sub.add_parser("remove-device")
r.add_argument("name")
args = ap.parse_args()

if args.cmd == "add-device":
    code = guard.new_enroll_code(args.name, args.hours)
    print(f"{args.base.rstrip('/')}/enroll/{code}")
elif args.cmd == "remove-device":
    print(f"removed {guard.remove_device(args.name)} device(s)")
else:
    d = guard.list_devices()
    for x in d["devices"]:
        print(f"device  {x['name']:20} enrolled {time.strftime('%Y-%m-%d', time.localtime(x['created']))}")
    for x in d["enroll"]:
        print(f"pending {x['name']:20} expires  {time.strftime('%Y-%m-%d %H:%M', time.localtime(x['expires']))}")
