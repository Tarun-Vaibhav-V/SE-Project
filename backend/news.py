"""Local water-risk news signals (NewsAPI) + sentiment/gov-action tagging.

The clippings are fetched for the site's region, focused on the site's
HIGHEST-scoring risk. Tagging runs through Groq (single JSON call, grounded on
the provided headlines only) with a deterministic keyword fallback — items and
URLs always come verbatim from NewsAPI, never generated.
"""
import json
import os
import time

import httpx

RISK_KEYWORDS = {
    "drought": '(drought OR "water scarcity" OR "water crisis")',
    "flood": '(flood OR flooding OR inundation OR waterlogging)',
    "groundwater": '(groundwater OR borewell OR aquifer OR "water table")',
    "scarcity": '("water shortage" OR "water supply" OR reservoir OR "water stress")',
    "quality": '("water pollution" OR "water quality" OR sewage OR effluent)',
}

NEG_WORDS = ("crisis", "shortage", "severe", "alarm", "deplet", "contaminat", "dead",
             "drought", "flood", "damage", "scarcity", "protest", "fail", "dry", "drown")
POS_WORDS = ("relief", "improve", "recover", "revive", "restored", "surplus", "success")
GOV_WORDS = ("government", "minister", "ministry", "scheme", "project", "approved",
             "tribunal", "board", "corporation", "policy", "authority", "municipal",
             "court", "budget", "plan", "launch")

_cache: dict = {}  # key -> (ts, payload); simple per-process TTL cache
TTL = 1800


def _keyword_tag(items):
    out = []
    for it in items:
        text = f'{it.get("title","")} {it.get("description","")}'.lower()
        neg = sum(w in text for w in NEG_WORDS)
        pos = sum(w in text for w in POS_WORDS)
        out.append({
            "sentiment": "negative" if neg > pos else "positive" if pos > neg else "neutral",
            "gov_action": any(w in text for w in GOV_WORDS),
        })
    return out, None


def _groq_tag(items, risk, place):
    """One JSON-mode call: sentiment + gov-action per item + 2-sentence summary.
    Only tags/summarizes the given items — indices must map back verbatim."""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    payload = [{"i": i, "title": it.get("title"), "description": (it.get("description") or "")[:200]}
               for i, it in enumerate(items)]
    resp = client.chat.completions.create(
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0.0, max_tokens=700,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content":
             "You tag news headlines about local water risk. Return JSON: "
             '{"items":[{"i":<index>,"sentiment":"negative|neutral|positive","gov_action":true|false}],'
             '"summary":"<=2 sentences on the overall signal and any government response>"}. '
             "negative = the item signals water stress/damage. gov_action = the item describes "
             "government/official measures. Tag ONLY the provided items; never mention items "
             "that are not in the input."},
            {"role": "user", "content": json.dumps({"risk": risk, "place": place, "items": payload})},
        ],
    )
    parsed = json.loads(resp.choices[0].message.content)
    tags = [{"sentiment": "neutral", "gov_action": False} for _ in items]
    for t in parsed.get("items", []):
        i = t.get("i")
        if isinstance(i, int) and 0 <= i < len(items):
            tags[i] = {"sentiment": t.get("sentiment", "neutral"),
                       "gov_action": bool(t.get("gov_action"))}
    return tags, parsed.get("summary")


def local_news(place: str, risk: str, page_size: int = 10):
    """place: e.g. 'Chennai' or 'Tamil Nadu India'; risk: highest-scoring risk key."""
    key = (place.lower(), risk)
    now = time.time()
    if key in _cache and now - _cache[key][0] < TTL:
        return _cache[key][1]

    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        return {"error": "NEWS_API_KEY not configured", "items": []}

    def fetch(q):
        # searchIn=title,description keeps matches visible-topic-relevant —
        # default NewsAPI matching hits article BODY text and returns noise
        r = httpx.get("https://newsapi.org/v2/everything",
                      params={"q": q, "language": "en", "sortBy": "publishedAt",
                              "searchIn": "title,description",
                              "pageSize": page_size, "apiKey": api_key},
                      timeout=20)
        b = r.json()
        return b if b.get("status") == "ok" else {"articles": [], "error": b.get("message")}

    kw = RISK_KEYWORDS.get(risk, RISK_KEYWORDS["scarcity"])
    q = f'"{place}" AND {kw}'
    body = fetch(q)
    if body.get("error"):
        return {"error": body["error"], "items": [], "query": q}

    raw = body.get("articles", [])
    if not raw:  # widen topic but stay water-related and place-anchored
        q = f'"{place}" AND (water OR river OR rain OR monsoon OR reservoir)'
        raw = fetch(q).get("articles", [])

    items = [{"title": a.get("title"), "description": a.get("description"),
              "source": (a.get("source") or {}).get("name"), "url": a.get("url"),
              "publishedAt": a.get("publishedAt")} for a in raw[:page_size]]

    summary = None
    engine = "keyword"
    try:
        if items and os.environ.get("GROQ_API_KEY"):
            tags, summary = _groq_tag(items, risk, place)
            engine = "groq"
        else:
            tags, _ = _keyword_tag(items)
    except Exception:
        tags, _ = _keyword_tag(items)
    for it, t in zip(items, tags):
        it.update(t)

    payload = {"place": place, "risk": risk, "query": q, "engine": engine,
               "summary": summary, "items": items,
               "note": "clippings verbatim from NewsAPI; tags/summary generated only from these items"}
    _cache[key] = (now, payload)
    return payload
