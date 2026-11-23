"""The language of a question: English, Polish, German, Spanish or French by letters and common words,
English when unsure. Code paths use it to answer in the question's language; the models get it as a hint and
answer any language themselves."""

from __future__ import annotations

import re

NAMES = {"en": "English", "pl": "Polish", "de": "German", "es": "Spanish", "fr": "French"}
LETTERS = {"pl": "ąćęłńśźż", "de": "äöüß", "es": "ñ¿¡", "fr": "çèêëàâîïôûœ"}
WORDS = {
    "en": "the what is are where which who how can do does show me my of for and in to there",
    "pl": "co gdzie jak jest czy się sie pokaż pokaz proszę prosze jakie które ktore dlaczego mogę moge"
    " mozesz możesz opisz wody dla na nie tak teraz jaki jaka",
    "de": "was wo wie ist sind gibt es der die das ich finde zeige mir und für über ein eine welche wann",
    "es": "qué que dónde donde cómo como es son hay el la los las muestra me para por una un cuál cuando del",
    "fr": "quoi où comment est sont il y a le la les je trouve montre moi pour une un quel quelle des du veut"
    " dire signifie puis-je puis sur avis quels quelles cette",
}
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def language_of(text: str) -> str:
    lower = text.lower()
    scores = {lang: 0.0 for lang in NAMES}
    for lang, letters in LETTERS.items():
        scores[lang] += 2.0 * sum(lower.count(c) for c in letters)
    tokens = WORD_RE.findall(lower)
    for lang, words in WORDS.items():
        vocab = set(words.split())
        scores[lang] += sum(1.0 for t in tokens if t in vocab)
    best = max(scores, key=lambda k: (scores[k], k == "en"))
    return best if scores[best] > scores["en"] else "en"


def name(code: str) -> str:
    return NAMES.get(code[:2], code)
