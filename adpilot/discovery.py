"""Optional YouTube Data API v3 discovery of relevant PUBLIC videos.

Key facts this module respects:
* A search result is a public video, NOT proof of a paid ad. Status is evidence-based:
  "Relevant Public Video" < "Potential Advertising Creative" < "Verified Ad" (only after a
  human records an independent source, e.g. Google Ads Transparency Center).
* No scraping, no unofficial endpoints. Only documented endpoints: search.list and videos.list.
* The API key is read from YOUTUBE_API_KEY on the server and is never sent to the browser.
* Nothing is fabricated: no key => no results, with an explanation.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
WATCH_URL = "https://www.youtube.com/watch?v="
TRANSPARENCY_URL = "https://adstransparency.google.com/"
# Quota facts (default project quota 10,000 units/day; verify in your Google Cloud console):
SEARCH_COST, VIDEOS_COST = 100, 1
MAX_CACHE_SECONDS = 30 * 24 * 3600  # YouTube developer policy: delete or refresh stored API data within 30 calendar days.
DAILY_QUOTA_DEFAULT = 10_000  # default per Google Cloud project; confirm in the Cloud Console
AUTO_SEARCHES = 3  # searches run automatically (about 300 units); the user can run more

STATUS_PUBLIC, STATUS_POTENTIAL, STATUS_VERIFIED = "Relevant Public Video", "Potential Advertising Creative", "Verified Paid Ad"


class DiscoveryError(Exception):
    code = "error"
    def __init__(self, message, code=None):
        super().__init__(message)
        if code: self.code = code


class MissingKeyError(DiscoveryError): code = "missing_key"
class InvalidKeyError(DiscoveryError): code = "invalid_key"
class QuotaError(DiscoveryError): code = "quota_exceeded"
class NetworkError(DiscoveryError): code = "network"


STOP = {"the", "and", "for", "with", "aged", "age", "a", "an", "of", "to", "in", "on", "who", "that", "is", "are", "my", "our", "your", "from", "at", "by"}


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2]


# ---------------------------------------------------------------- URL parsing
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}


def parse_youtube_url(raw):
    """Validate a YouTube link and extract the 11-character video ID safely.

    Supports watch?v=, youtu.be/, /shorts/, /embed/, /live/ and /v/ links. Never fetches the URL.
    """
    raw = (raw or "").strip()
    if not raw:
        return {"ok": False, "code": "empty", "error": "Paste a YouTube video link, or leave this empty."}
    if len(raw) > 300 or any(c in raw for c in " \t\n\r<>\"'"):
        return {"ok": False, "code": "invalid", "error": "That does not look like a single web link. Paste just the YouTube video link."}
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    try:
        u = urllib.parse.urlparse(raw)
    except ValueError:
        return {"ok": False, "code": "invalid", "error": "That link could not be read."}
    host = (u.hostname or "").lower()
    if host not in YT_HOSTS:
        return {"ok": False, "code": "not_youtube", "error": "Only YouTube links are supported (youtube.com, youtu.be)."}
    path, vid, kind = u.path or "", None, "watch"
    if host.endswith("youtu.be"):
        vid = path.strip("/").split("/")[0] if path.strip("/") else None
    elif path == "/watch":
        vid = (urllib.parse.parse_qs(u.query).get("v") or [None])[0]
    else:
        m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", path)
        if m:
            kind, vid = ("shorts" if m.group(1) == "shorts" else "watch"), m.group(2)
        elif re.match(r"^/(playlist|channel|c|user|@)", path):
            return {"ok": False, "code": "not_video", "error": "This looks like a channel or playlist link. Paste a link to one video."}
    if not vid or not YT_ID.match(vid):
        return {"ok": False, "code": "invalid", "error": "No valid video ID was found in that link. Check that you copied the whole address."}
    return {"ok": True, "video_id": vid, "kind": kind, "url": WATCH_URL + vid}


def safe_youtube_url(raw):
    """Canonical watch URL for a valid YouTube link, else None. Used before any URL is stored or rendered."""
    p = parse_youtube_url(raw)
    return p["url"] if p["ok"] else None


# ---------------------------------------------------------------- query generation
def _jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 1.0


def generate_queries(profile: dict, concepts=None, limit: int = 8) -> list:
    """Build distinct, explainable searches from the profile (and chosen concepts). Ordered by usefulness.

    The first AUTO_SEARCHES items are the ones run automatically, because each search costs 100 quota units.
    """
    product = (profile.get("product") or "").strip()
    if not product:
        return []  # a search with no product term would be too generic to be useful
    industry = (profile.get("industry_label") or "").strip()
    industry = "" if industry.lower() in ("other", "") else industry
    brand = (profile.get("brand") or "").strip()
    audience = (profile.get("audience") or "").strip()
    market = (profile.get("market") or "").strip()
    objective = profile.get("objective", "")
    problem = (profile.get("problem") or "").strip()
    benefit = (profile.get("benefit") or "").strip()
    cands = [(f"{product} commercial", "Brand commercials for your product type")]
    focus = problem or benefit
    if focus:
        cands.append((f"{focus} {product}", "Videos about the problem or benefit your product addresses"))
    if market:
        cands.append((f"{product} ad {market}", "Videos aimed at your market"))
    approach_q = {"demonstration": ("how to use {p} demonstration", "Product-demonstration style videos"),
                  "customer_story": ("{p} customer story review", "Customer-story style videos (often organic, useful for tone)"),
                  "problem_solution": ("{p} problem solution video", "Problem-and-solution style videos"),
                  "offer_led": ("{p} offer promotion video", "Offer-led promotional videos"),
                  "explainer": ("how to choose {p}", "Explainer and guidance videos")}
    for c in (concepts or []):
        q = approach_q.get(c.get("archetype"))
        if q:
            cands.append((q[0].format(p=product), q[1]))
    if industry:
        cands.append((f"{industry} brand video advertisement {product}", "Same category and product together"))
    short_aud = " ".join(tokens(audience)[:3])
    if short_aud:
        cands.append((f"{product} for {short_aud}", "Audience-specific phrasing"))
    if objective in ("sales", "leads"):
        cands.append((f"buy {product} official ad", "Videos with a purchase-style message"))
    elif objective in ("awareness", "reach", "engagement"):
        cands.append((f"{product} brand film", "Story-led brand videos"))
    cands.append((f"competing {product} brand campaign", "Brands competing for the same buyers"))
    if brand:
        cands.append((f"{brand} {product} ad", "Your own brand's phrasing, for comparison"))
    out, seen = [], []
    for q, why in cands:
        q = re.sub(r"\s+", " ", q).strip()
        t = frozenset(tokens(q))
        if any(_jaccard(t, s) >= 0.75 for s in seen):
            continue  # near-duplicate of a query we already have
        seen.append(t); out.append({"query": q, "reason": why})
    return out[:limit]


# ---------------------------------------------------------------- HTTP + client
def default_http_get(url: str, params: dict, timeout: float = 15.0):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json", "User-Agent": "AdPilot/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkError(f"Could not reach the YouTube API ({e.__class__.__name__}). Check your internet connection and try again.")


def _raise_for(status, body):
    err = (body or {}).get("error", {})
    reasons = [e.get("reason", "") for e in err.get("errors", [])] if isinstance(err, dict) else []
    msg = err.get("message", "") if isinstance(err, dict) else ""
    if status == 200:
        return
    if any(r in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded") for r in reasons):
        raise QuotaError("The YouTube API daily quota is used up. Try again after it resets (midnight Pacific time) or use manual / sample data.")
    if (any(r in ("keyInvalid", "badRequest") for r in reasons) and "key" in msg.lower()) or (status in (400, 401) and "API key" in msg):
        raise InvalidKeyError("The YouTube API key was rejected. Check YOUTUBE_API_KEY in your .env file.")
    if status == 403:
        raise InvalidKeyError("Access was denied (HTTP 403). Make sure YouTube Data API v3 is enabled for the key's Google Cloud project and that the key's restrictions allow it.")
    raise DiscoveryError(f"The YouTube API returned an error ({status}). {msg}".strip(), "api_error")


class YouTubeClient:
    def __init__(self, api_key=None, http_get=None):
        self.api_key = api_key if api_key is not None else os.environ.get("YOUTUBE_API_KEY", "")
        self.http_get = http_get or default_http_get

    @property
    def configured(self):
        k = (self.api_key or "").strip()
        return bool(k) and not k.lower().startswith(("your_", "paste", "changeme", "xxx"))

    def search(self, query, max_results=10, page_token=None, region=None, published_after=None):
        if not self.configured:
            raise MissingKeyError("YouTube discovery is switched off because no API key is set. Add YOUTUBE_API_KEY to your .env file, or use manual and sample data.")
        params = {"part": "snippet", "type": "video", "q": query, "maxResults": max(1, min(int(max_results), 25)), "key": self.api_key, "safeSearch": "moderate"}
        if page_token: params["pageToken"] = page_token
        if region: params["regionCode"] = region
        if published_after: params["publishedAfter"] = published_after
        status, body = self.http_get(SEARCH_URL, params)
        _raise_for(status, body)
        items = (body or {}).get("items", []) or []
        ids = [it.get("id", {}).get("videoId") for it in items if isinstance(it.get("id"), dict) and it["id"].get("videoId")]
        details = self.video_details(ids) if ids else {}
        videos = []
        for it in items:
            vid = (it.get("id") or {}).get("videoId") if isinstance(it.get("id"), dict) else None
            if not vid:
                continue
            videos.append(normalise_video(vid, it.get("snippet") or {}, details.get(vid), vid in details))
        return {"videos": videos, "next_page_token": (body or {}).get("nextPageToken"), "quota_units": SEARCH_COST + (VIDEOS_COST if ids else 0)}

    def video_details(self, ids):
        status, body = self.http_get(VIDEOS_URL, {"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids[:50]), "key": self.api_key})
        _raise_for(status, body)
        return {it["id"]: it for it in (body or {}).get("items", []) if it.get("id")}


def _iso_duration_seconds(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m: return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def normalise_video(video_id, search_snippet, detail, detail_found):
    """Merge search + videos.list data. Missing fields stay None; nothing is invented."""
    sn = {**search_snippet, **((detail or {}).get("snippet") or {})}
    stats = (detail or {}).get("statistics") or {}
    thumbs = sn.get("thumbnails") or {}
    thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
    def _int(x):
        try: return int(x)
        except (TypeError, ValueError): return None
    return {
        "video_id": video_id, "url": WATCH_URL + video_id, "title": sn.get("title"), "description": sn.get("description") or "",
        "channel_title": sn.get("channelTitle"), "channel_id": sn.get("channelId"), "published_at": sn.get("publishedAt"),
        "thumbnail": thumb, "duration_seconds": _iso_duration_seconds(((detail or {}).get("contentDetails") or {}).get("duration")),
        "tags": sn.get("tags") or [],
        # public engagement numbers: context only, never ad performance
        "public_views": _int(stats.get("viewCount")), "public_likes": _int(stats.get("likeCount")), "public_comments": _int(stats.get("commentCount")),
        "details_available": bool(detail_found),
        "made_for_kids": ((detail or {}).get("status") or {}).get("madeForKids"),
    }


# ---------------------------------------------------------------- relevance + classification
TITLE_AD_TERMS = ["commercial", "advertisement", "advert", " tvc", "tv spot", "tv ad", "official ad", " ad ", " ad:", "brand film", "campaign"]
DESC_AD_TERMS = ["advertisement", "commercial", "tvc", "tv spot"]
WEAK_CTA = ["shop now", "buy now", "order now", "available at", "get yours", "book now", "sign up", "link below", "visit our"]
WEAK_OFFER = ["% off", "sale", "discount", "free delivery", "limited time", "coupon", "promo code"]
REVIEW_TERMS = ["review", "unboxing", "reaction", "tutorial", "how to", "vlog", "haul", "tested", "routine", "tips"]
RELEVANCE_METHOD = ("Match score 0-100 from text overlap only: product terms (45), category terms (15), audience terms (15), problem/benefit terms (10), market (5), "
                    "advertising wording in the title (10). Popularity (views, likes) is deliberately NOT used.")


def score_relevance(video, ctx, queries=None):
    """0-100 match score with a plain-language reason. Based only on text overlap; popularity is ignored."""
    text = " ".join([video.get("title") or "", video.get("description") or "", " ".join(video.get("tags") or []), video.get("channel_title") or ""]).lower()
    toks = set(tokens(text))
    parts, reasons = 0.0, []
    def part(terms, weight, label, cap=None):
        nonlocal parts
        terms = set(terms)
        if not terms:
            return
        hit = terms & toks
        frac = min(len(hit), cap) / cap if cap else len(hit) / len(terms)
        parts += weight * frac
        if hit:
            reasons.append(f"{label} ({', '.join(sorted(hit)[:4])})")
    part(tokens(ctx.get("product", "")), 45, "mentions your product terms")
    part(tokens(ctx.get("industry_label", "")), 15, "matches your category")
    part(tokens(ctx.get("audience", "")), 15, "overlaps with your audience description", cap=3)
    part(tokens((ctx.get("problem") or "") + " " + (ctx.get("benefit") or "")), 10, "touches the problem or benefit you described", cap=3)
    part(tokens(ctx.get("market", "")), 5, "mentions your market")
    t = " " + (video.get("title") or "").lower() + " "
    if any(a in t for a in TITLE_AD_TERMS):
        parts += 10; reasons.append("title looks like an advertisement or promo")
    if not reasons:
        reasons.append("was returned by the search but shares few terms with your profile")
    return {"relevance": int(min(100, round(parts))), "why": "Selected because it " + "; ".join(reasons) + "."}


def classify_video(video, ctx, manual_verification=None):
    """Return {status, evidence[], verification_note}. NEVER marks a paid ad automatically.

    Potential Advertising Creative needs advertising wording in the title/description, or a promotional
    call to action together with an offer. Links, channel names and view counts are not evidence.
    """
    ev = []
    if manual_verification and manual_verification.get("verified"):
        src = (manual_verification.get("source") or "").strip()
        if src:
            return {"status": STATUS_VERIFIED, "evidence": [f"You recorded this as a paid ad, citing: {src}."],
                    "verification_note": "Recorded manually by you from the source above. AdPilot cannot check this automatically, and it still has no performance data for the video.",
                    "verification_method": "manual", "transparency_url": TRANSPARENCY_URL}
        ev.append("A verification was requested but no source was entered, so it was not accepted.")
    title = " " + (video.get("title") or "").lower() + " "
    desc = (video.get("description") or "").lower()
    strong = [t.strip() for t in TITLE_AD_TERMS if t in title]
    strong_d = [t for t in DESC_AD_TERMS if t in desc]
    cta = [t for t in WEAK_CTA if t in desc or t in title]
    offer = [t for t in WEAK_OFFER if t in desc or t in title]
    organic = [t for t in REVIEW_TERMS if t in title]
    if strong: ev.append(f"Title uses advertising wording ({', '.join(strong[:3])}).")
    if strong_d: ev.append(f"Description uses advertising wording ({', '.join(strong_d[:3])}).")
    if cta and offer: ev.append(f"Description has both a purchase call to action ({cta[0]}) and an offer ({offer[0]}).")
    elif cta or offer: ev.append("Has a promotional phrase on its own, which is too weak to suggest advertising.")
    if organic: ev.append(f"Title looks like organic content ({', '.join(organic[:2])}), which counts against it being an ad.")
    promo = bool(strong or strong_d or (cta and offer))
    if promo and not (organic and not strong):
        status = STATUS_POTENTIAL
        note = "Looks like brand or promotional creative, but nothing proves it is or was a paid YouTube ad. Check the Google Ads Transparency Center."
    else:
        status = STATUS_PUBLIC
        note = "A relevant public video. There is no evidence that it is advertising."
    ev.append("The YouTube API does not say whether a video is a paid ad. Views and likes shown are public statistics, not advertising results.")
    return {"status": status, "evidence": ev, "verification_note": note, "verification_method": "none", "transparency_url": TRANSPARENCY_URL}


def dedupe(videos):
    seen, out = set(), []
    for v in videos:
        if v["video_id"] in seen: continue
        seen.add(v["video_id"]); out.append(v)
    return out


# ---------------------------------------------------------------- cache
class DiscoveryCache:
    def __init__(self, directory, ttl_seconds=6 * 3600):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = min(int(ttl_seconds), MAX_CACHE_SECONDS)

    def _path(self, key):
        return self.dir / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")

    def get(self, key):
        p = self._path(key)
        if not p.exists(): return None
        try:
            data = json.loads(p.read_text())
        except Exception:
            return None
        if time.time() - data.get("fetched_at", 0) > self.ttl:
            try: p.unlink()
            except OSError: pass
            return None
        return data

    def set(self, key, payload):
        data = {"fetched_at": time.time(), **payload}
        self._path(key).write_text(json.dumps(data))
        return data

    def purge_expired(self):
        n = 0
        for p in self.dir.glob("*.json"):
            try:
                if time.time() - json.loads(p.read_text()).get("fetched_at", 0) > self.ttl:
                    p.unlink(); n += 1
            except Exception: pass
        return n


class QuotaTracker:
    """Local estimate of quota units this app has spent today (Pacific time, when YouTube's quota resets).

    Other tools sharing the same Google Cloud project are not counted, so the Cloud Console remains authoritative.
    """
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def today():
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        except Exception:
            return (datetime.now(timezone.utc) - timedelta(hours=8)).date().isoformat()

    def _read(self):
        try:
            d = json.loads(self.path.read_text())
            return d if d.get("day") == self.today() else {"day": self.today(), "units": 0}
        except Exception:
            return {"day": self.today(), "units": 0}

    def used(self):
        return self._read()["units"]

    def add(self, units):
        d = self._read(); d["units"] += int(units)
        try: self.path.write_text(json.dumps(d))
        except OSError: pass
        return d["units"]

    def snapshot(self):
        return {"estimated_units_used_today": self.used(), "assumed_daily_quota": DAILY_QUOTA_DEFAULT,
                "note": "Estimate of what AdPilot spent today (Pacific time). Other apps on the same Google Cloud project are not counted; the Cloud Console is authoritative."}


def lookup_video(client, cache, url, ctx, quota=None):
    """Optional competitor URL: validate, then fetch public metadata with videos.list (1 quota unit).

    Returns a dict with retrieved True/False and a plain-language message; raises DiscoveryError only for invalid URLs.
    """
    p = parse_youtube_url(url)
    if not p["ok"]:
        raise DiscoveryError(p["error"], "invalid_url")
    vid = p["video_id"]
    explain = ("From a link AdPilot can read the public title, description, channel, publish date, duration and public view/like counts, when the video is public. "
               "It cannot read the spoken words, visuals, private analytics, or whether the video is a paid ad. Paste a transcript to enable deeper text analysis.")
    base = {"video_id": vid, "url": p["url"], "explain": explain}
    if not client.configured:
        return {**base, "retrieved": False, "reason": "missing_key",
                "message": "No YouTube API key is configured, so no details could be retrieved. The link was accepted and can be added by hand with your own notes."}
    key = "video:" + vid
    cached = cache.get(key)
    if cached:
        video, ts = cached["video"], cached["fetched_at"]
    else:
        detail = client.video_details([vid]).get(vid)
        if quota: quota.add(VIDEOS_COST)
        if not detail:
            return {**base, "retrieved": False, "reason": "unavailable",
                    "message": "YouTube did not return this video. It may be private, deleted, region-restricted, or the link may be mistyped. You can still add it by hand with your own notes."}
        video = normalise_video(vid, {}, detail, True)
        ts = cache.set(key, {"video": video})["fetched_at"]
    video = {**video, "retrieved_at": ts, "source": "youtube_api"}
    video.update(score_relevance(video, ctx)); video.update(classify_video(video, ctx))
    return {**base, "retrieved": True, "video": video, "message": "Public details retrieved from the YouTube API."}


def discover(client: YouTubeClient, cache: DiscoveryCache, ctx: dict, queries: list, per_query=8, refresh=False, region=None, page_tokens=None, quota=None) -> dict:
    """Run queries, merge, dedupe, score and classify. Returns results + provenance (when retrieved, quota)."""
    page_tokens = page_tokens or {}
    all_videos, errors, spent, retrieved, from_cache = [], [], 0, [], 0
    for q in queries:
        key = json.dumps([q, per_query, region, page_tokens.get(q)])
        cached = None if refresh else cache.get(key)
        if cached:
            res, ts = cached, cached["fetched_at"]; from_cache += 1
        else:
            try:
                res = client.search(q, per_query, page_tokens.get(q), region)
            except MissingKeyError:
                raise
            except DiscoveryError as e:
                errors.append({"query": q, "code": e.code, "message": str(e)})
                if isinstance(e, (QuotaError, InvalidKeyError)):
                    break
                continue
            data = cache.set(key, {"videos": res["videos"], "next_page_token": res["next_page_token"], "quota_units": res["quota_units"]})
            ts = data["fetched_at"]; spent += res["quota_units"]
            if quota: quota.add(res["quota_units"])
        retrieved.append(ts)
        for v in res["videos"]:
            all_videos.append({**v, "matched_query": q, "retrieved_at": ts, "source": "youtube_api"})
    videos = dedupe(all_videos)
    dropped = [v for v in videos if not v.get("details_available")]
    videos = [v for v in videos if v.get("details_available")]  # deleted/private/unavailable items are dropped, and counted
    for v in videos:
        v.update(score_relevance(v, ctx)); v.update(classify_video(v, ctx))
    videos.sort(key=lambda v: -v["relevance"])
    return {"videos": videos, "unavailable_count": len(dropped), "errors": errors, "quota_units_used": spent, "relevance_method": RELEVANCE_METHOD, "served_from_cache": from_cache,
            "retrieved_at": min(retrieved) if retrieved else None, "queries": queries}


def sort_and_filter(videos, sort="relevance", status=None, published_after=None, min_relevance=0):
    out = [v for v in videos if v.get("relevance", 0) >= min_relevance]
    if status: out = [v for v in out if v.get("status") == status]
    if published_after: out = [v for v in out if (v.get("published_at") or "") >= published_after]
    key = {"relevance": lambda v: -v.get("relevance", 0), "date": lambda v: v.get("published_at") or "", "title": lambda v: (v.get("title") or "").lower()}[sort]
    return sorted(out, key=key, reverse=(sort == "date"))
