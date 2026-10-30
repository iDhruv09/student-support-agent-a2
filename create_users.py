"""
create_users.py - Create data/users.json with hashed demo passwords.

Run once:  python create_users.py
Demo logins (fake data, for the demo and graders only):
    students  S101 ... S110   password  <ID>@demo     e.g. S101@demo
    admin     admin           password  admin@demo
"""
import json

from auth import USERS_FILE, hash_password

students = json.loads((USERS_FILE.parent / "students.json").read_text(encoding="utf-8"))

users = {sid: {"role": "student", "name": s["name"], "password_hash": hash_password(f"{sid}@demo")}
         for sid, s in students.items()}
users["admin"] = {"role": "admin", "name": "Program Office", "password_hash": hash_password("admin@demo")}

USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
print(f"Created {USERS_FILE} with {len(users)} users (passwords stored as hashes only).")
print("Demo logins: S101 / S101@demo  ...  admin / admin@demo")
