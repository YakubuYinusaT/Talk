"""Text normalisation, spoken numbers, phone numbers and word error rate."""

import re
import unicodedata

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "dozen": 12,
}


def clean(text: str) -> str:
    """Lower case, plain letters and digits, single spaces. A recogniser may write a letter with an accent or a mark under it: every letter is reduced to its
    plain Latin base FIRST, otherwise those letters would be deleted below and the words destroyed."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.lower().replace("'", "")
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 9,500 -> 9500
    text = re.sub(r"[^a-z0-9\s.]", " ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def e164(number: str) -> str:
    n = re.sub(r"[\s\-()]", "", number or "")
    if n.startswith("+"):
        return n
    if n.startswith("234"):
        return "+" + n
    if n.startswith("0"):
        return "+234" + n[1:]
    return "+" + n if n else n


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: word-level edit distance divided by the reference length."""
    r, h = clean(reference).split(), clean(hypothesis).split()
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)
