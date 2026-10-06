"""
textvec.py — tiny, dependency-free text vectors so shadow + breaker run with no model.

embed() is a stable hashing bag-of-words, L2-normalized; cosine() is a dot product.
This is a STAND-IN for real embeddings. In production, replace embed() with
sentence-transformers or an embeddings endpoint and nothing else changes — the breaker and
scorer only call embed()/cosine(). The hash is stable across runs (blake2b), unlike Python's
salted hash(), so distances are reproducible.
"""
import hashlib, math, re

DIM = 256
_TOK = re.compile(r"[a-z0-9']+")
STOP = set("the a an and or to of for is are was were be been you i we it this that your my our "
           "in on at with from your can will just please would could it's i'm we'll i'll".split())

def tokens(s): return _TOK.findall(s.lower())
def content_tokens(s): return [t for t in tokens(s) if t not in STOP]

def _h(t): return int(hashlib.blake2b(t.encode(), digest_size=4).hexdigest(), 16) % DIM

def embed(text, content_only=False):
    v = [0.0] * DIM
    for t in (content_tokens(text) if content_only else tokens(text)):
        v[_h(t)] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]

def cosine(a, b): return sum(x * y for x, y in zip(a, b))
def distance(a, b): return 1.0 - cosine(a, b)
