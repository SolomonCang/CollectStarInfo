"""Administrative CLI for local accounts."""

from __future__ import annotations

import argparse
from getpass import getpass
import json

from sqlalchemy.exc import IntegrityError

from .services.workspace_service import workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="Target Info workspace administration")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="Create the first administrator")
    create.add_argument("--username", required=True)
    create.add_argument("--password", help="Omit to enter the password securely")
    users = commands.add_parser("list-users", help="List local accounts")
    args = parser.parse_args()
    workspace.initialize()

    if args.command == "create-admin":
        password = args.password or getpass("Password: ")
        if not args.password:
            confirmation = getpass("Confirm password: ")
            if password != confirmation:
                parser.error("Passwords do not match")
        try:
            user = workspace.create_user(args.username, password, role="admin")
        except (ValueError, IntegrityError) as exc:
            parser.error(str(exc))
        print(json.dumps(user, ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-users":
        print(json.dumps(workspace.list_users(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
