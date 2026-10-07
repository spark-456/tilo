"""Prints the `tilo-api` user id for a Firebase uid (SEC-15, BQ-SIGNIN-9).

`TILO_PEOPLE_BOOTSTRAP_UID` must hold the user id the API gives the founder, which is not the Firebase uid: it is
`tilo_api.firebase_auth.user_id_for(uid)`. Find the uid in the Firebase console (Authentication, Users, "User UID"
column) after the founder has signed in once with Google, then:

    uv run python scripts/signin_user_id.py <firebase-uid>

and put the printed `u_...` value in `TILO_PEOPLE_BOOTSTRAP_UID` on the `tilo-api` service. Nothing is sent anywhere.
"""

from __future__ import annotations

import sys

from tilo_api.firebase_auth import user_id_for


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not 0 < len(argv[1]) <= 128:
        print("usage: signin_user_id.py <firebase-uid>  (1 to 128 characters)", file=sys.stderr)
        return 2
    print(user_id_for(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
