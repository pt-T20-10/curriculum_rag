"""Generate a bcrypt hash for DEFAULT_ADMIN_PASSWORD_HASH."""

from getpass import getpass

import bcrypt



def main() -> None:
    password = getpass("New admin password: ")
    confirmation = getpass("Confirm admin password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    encoded_password = password.encode("utf-8")
    if len(encoded_password) > 72:
        raise SystemExit("Password must not exceed bcrypt's 72-byte limit.")

    print("\nDEFAULT_ADMIN_PASSWORD_HASH=")
    print(bcrypt.hashpw(encoded_password, bcrypt.gensalt(rounds=12)).decode("utf-8"))


if __name__ == "__main__":
    main()
