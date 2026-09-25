import re

_PATTERNS = [
    (re.compile(r"(?i)(authorization|bearer)\s*[:=]\s*\S+"), r"\1: ***"),
    (re.compile(r"(eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*)"), "***"),
    (re.compile(r"(?i)((?:sk|api[_-]?key|token|secret|password)\s*[:=]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "***PHONE***"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "***EMAIL***"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S), "***PRIVATE KEY***"),
]


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text