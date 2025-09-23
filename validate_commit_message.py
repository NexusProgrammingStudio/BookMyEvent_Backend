#!/usr/bin/env python3
import re
import sys

# Define the allowed commit message format
COMMIT_MSG_FORMAT = r"^(feat|fix|chore|docs|style|refactor|test|ci|add): .+$"
ALLOWED_TYPES: list[str] = [
    "feat",
    "fix",
    "chore",
    "docs",
    "style",
    "refactor",
    "test",
    "ci",
    "add",
]  # noqa: E501


def validate_commit_message(message: str) -> bool:
    if not re.match(COMMIT_MSG_FORMAT, message):
        print("Error: Invalid commit message format.\n")
        print("Expected format: <type>: <description>")
        print(f"Allowed types: {', '.join(ALLOWED_TYPES)}")
        print(f"Your message: {message.strip()}\n")
        print("Example: feat: add new login feature")
        return False
    return True


def main() -> None:
    # Read the commit message from the file passed as an argument
    commit_msg_file: str = sys.argv[1]
    with open(commit_msg_file, "r") as file:
        commit_message: str = file.read().strip()

    if not validate_commit_message(commit_message):
        sys.exit(1)


if __name__ == "__main__":
    main()
