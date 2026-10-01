"""Connect a mailbox to a user's inbox (app/services/inbox.py): python scripts/inbox_connect.py <user_id> <address>
The app password is read from stdin (or from the .env provider that holds that address with --from-env), never printed.
--home <room_id> sets where items that belong to no room are said."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('user_id'); parser.add_argument('address', nargs='?')
    parser.add_argument('--from-env', action='store_true'); parser.add_argument('--home')
    args = parser.parse_args()
    from app.services import inbox
    if args.address:
        password = ''
        if args.from_env:
            from app.config import settings
            from app.services.imap_email_service import PROVIDERS
            for cfg in PROVIDERS.values():
                if (getattr(settings, cfg['address_attr'], '') or '').lower() == args.address.lower():
                    password = getattr(settings, cfg['password_attr'], '') or ''
        password = password or getpass.getpass('app password: ')
        print('connected:', inbox.connect_mailbox(args.user_id, args.address, password))
    if args.home:
        inbox.set_home_room(args.user_id, args.home); print('home room:', args.home)


if __name__ == '__main__':
    main()
