import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:\-]*|[\u4e00-\u9fff]")
_EMBED_DIM = 256
_CJK = re.compile(r"^[\u4e00-\u9fff]$")


def normalize(text: str) -> str:
    return re.sub(r"[\s，。；：！？、,.!?;:()（）\[\]【】\"'“”‘’\-—_~]+", "", text or "").lower()


def tokenize(text: str) -> list:
    text = text or ""
    units = _TOKEN_RE.findall(text.lower())
    tokens = []
    prev = None
    for u in units:
        tokens.append(u)
        if _CJK.match(u):
            if prev and _CJK.match(prev):
                tokens.append(prev + u)
            prev = u
        else:
            prev = None
    return tokens


def embed(text: str) -> list:
    vec = [0.0] * _EMBED_DIM
    for tok in tokenize(text):
        idx = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % _EMBED_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b))
