"""
privacy.py - Sensitive-data redaction for the Student Support Agent (Assignment 2).

redact(text) replaces OTPs, passwords, PINs, CVVs, verification codes and long
card / account / Aadhaar numbers with [REDACTED].

It is applied to the student's message BEFORE it reaches:
  the LLM, long-term memory, the trace file, the audit log and the stored chat history.
So a secret typed in the chat is never stored anywhere, not even in logs.

Normal data is kept: 10-digit phone numbers, amounts (Rs 1,00,000), dates, student IDs.
"""
import re

MASK = "[REDACTED]"

# keyword + value:  "OTP is 482913", "password: abc@123", "pwd=hello1", "PIN 4321", "मेरा OTP 739201"
_KEYWORD_VALUE = re.compile(
    r"\b(otp|one[- ]time password|password|passwd|pwd|passcode|pin|upi pin|cvv|cvc|"
    r"verification code|security code|login code|auth code)\b"
    r"(\s*(?:is|was|:|=|-)?\s*)"
    r"([^\s,.;!?]+)",
    re.IGNORECASE)

# long card / account / Aadhaar numbers, with or without spaces or dashes (12-19 digits)
_LONG_NUMBER = re.compile(r"\b(?:\d[ -]?){11,18}\d\b")

# if the message talks about a secret, any short stand-alone code (4-8 digits) is masked too:
# "482913 is the code I got", "use 5521 to log in, it is my pin"
_SECRET_HINT = re.compile(r"\b(otp|code|password|passwd|pwd|passcode|pin|cvv|verification)\b|ओटीपी|पासवर्ड", re.IGNORECASE)
_SHORT_CODE = re.compile(r"(?<![\d,.])\b\d{4,8}\b(?![\d,.])")


def redact(text):
    """Return text with secrets replaced by [REDACTED]. Safe on None and non-strings."""
    if not isinstance(text, str) or not text:
        return text
    out = _LONG_NUMBER.sub(MASK, text)
    out = _KEYWORD_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    if _SECRET_HINT.search(text):
        out = _SHORT_CODE.sub(MASK, out)
    return out


def contains_secret(text):
    """True if redact() would change the text (used to flag the trace and audit)."""
    return isinstance(text, str) and redact(text) != text


def redact_deep(value):
    """Redact every string inside dicts / lists (for traces and audit details)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_deep(v) for v in value]
    return value
