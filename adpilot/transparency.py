"""Optional third-party Google Ads Transparency Center integration.

Provider: SearchApi (https://www.searchapi.io). Three documented engines are used:
  google_ads_transparency_center_advertiser_search   keyword -> advertisers / domains
  google_ads_transparency_center                     advertiser_id or domain -> ad creatives (no video ID in this list)
  google_ads_transparency_center_ad_details          advertiser_id + creative_id -> variations, some with video_id / video_link

What the evidence can and cannot prove (this is the core design rule):
* EXACT  - an 11-character YouTube video ID returned by the provider equals the ID of a discovered video.
           Only this can produce "Verified Paid Ad" automatically.
* POSSIBLE - same advertiser name AND similar creative text but NO matching video ID. Never verified.
* Everything else is "Unverified" (or "Not checked" when the provider could not be used). Absence of a match
  is NOT proof that a video was never an ad: only a limited number of creatives is inspected per run.

The provider is isolated behind a small interface (search_advertisers / list_creatives / creative_details), so another
provider can be added by writing one class that returns the same normalised dictionaries.
The API key is read from SEARCHAPI_API_KEY, sent in an Authorization header (never in a URL), and never returned or logged.
"""
from __future__ import annotations
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import discovery as D

PROVIDER = "searchapi"
PROVIDER_LABEL = "SearchApi (Google Ads Transparency Center data)"
ENV_KEY = "SEARCHAPI_API_KEY"
BASE_URL = "https://www.searchapi.io/api/v1/search"
TRANSPARENCY_HOME = "https://adstransparency.google.com/"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_MAX_DETAILS, MAX_DETAILS_CAP = 10, 25
DEFAULT_MAX_ADVERTISERS, MAX_ADVERTISERS_CAP = 3, 6
LIST_PAGE_SIZE = 40  # documented default; one page per advertiser
NAME_MATCH_MIN = 0.6

STATES = {"verified_exact", "possible_match", "unverified", "not_checked"}
STATE_LABEL = {"verified_exact": "Verified: exact video ID match", "possible_match": "Possible match (not verified)",
               "unverified": "Unverified", "not_checked": "Not checked"}


# ---------------------------------------------------------------- errors
class TransparencyError(Exception):
    code = "error"
    def __init__(self, message, code=None):
        super().__init__(message)
        if code: self.code = code


class MissingKeyError(TransparencyError): code = "missing_key"
class InvalidKeyError(TransparencyError): code = "invalid_key"
class QuotaError(TransparencyError): code = "quota_exceeded"
class RateLimitError(TransparencyError): code = "rate_limited"
class NetworkError(TransparencyError): code = "network"
class ProviderError(TransparencyError): code = "provider_error"
class MalformedResponseError(TransparencyError): code = "malformed_response"


# ---------------------------------------------------------------- small validators
AR_RE, CR_RE = re.compile(r"^AR\d{6,30}$"), re.compile(r"^CR\d{6,30}$")
DOMAIN_RE = re.compile(r"^(?=.{4,100}$)([a-z0-9-]+\.)+[a-z]{2,}$", re.I)
SAFE_TU_RE = re.compile(r"^https://adstransparency\.google\.com/(\?region=[A-Za-z0-9]{1,8})?$|"
                        r"^https://adstransparency\.google\.com/advertiser/AR\d{6,30}(/creative/CR\d{6,30})?(\?region=[A-Za-z0-9]{1,8})?$")


def _s(v, n=300):
    return v.strip()[:n] if isinstance(v, str) and v.strip() else None


def _int(v):
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def normalise_region(raw):
    """'' / ANYWHERE / 0 -> 'ANYWHERE'; ISO alpha-2 (e.g. PK) or a 4-5 digit Google region code are kept. Else ValueError."""
    r = (raw or "").strip().upper()
    if r in ("", "ANYWHERE", "0"):
        return "ANYWHERE"
    if re.fullmatch(r"[A-Z]{2}", r) or re.fullmatch(r"\d{4,5}", r):
        return r
    raise ValueError("Region must be a two-letter country code such as PK, or left empty for anywhere.")


def transparency_url(advertiser_id=None, creative_id=None, region="ANYWHERE"):
    """Official Transparency Center link built by AdPilot from VALIDATED ids (provider-supplied links are never rendered)."""
    reg = "anywhere" if region in (None, "", "ANYWHERE") else region
    if advertiser_id and AR_RE.match(advertiser_id):
        base = f"{TRANSPARENCY_HOME}advertiser/{advertiser_id}"
        if creative_id and CR_RE.match(creative_id):
            base += f"/creative/{creative_id}"
        return f"{base}?region={reg}"
    return f"{TRANSPARENCY_HOME}?region={reg}"


def safe_transparency_url(u):
    return u if isinstance(u, str) and SAFE_TU_RE.match(u) else None


# ---------------------------------------------------------------- HTTP
def default_http_get(url, params, headers=None, timeout=25.0):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json", "User-Agent": "AdPilot/0.4", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                raise MalformedResponseError("SearchApi returned something that is not valid JSON.")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # only the exception class is reported: never the URL
        raise NetworkError(f"Could not reach SearchApi ({e.__class__.__name__}). Check your internet connection and try again.")


# ---------------------------------------------------------------- normalisation (tolerant of missing/odd fields)
def normalise_advertiser(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not AR_RE.match(raw["id"]):
        return None
    ac = raw.get("ads_count") if isinstance(raw.get("ads_count"), dict) else {}
    return {"advertiser_id": raw["id"], "name": _s(raw.get("name"), 150), "region": _s(raw.get("region"), 8), "is_verified": bool(raw.get("is_verified")),
            "ads_lower": _int(ac.get("lower")), "ads_upper": _int(ac.get("upper"))}


def normalise_creative(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not CR_RE.match(raw["id"]):
        return None
    adv = raw.get("advertiser") if isinstance(raw.get("advertiser"), dict) else {}
    adv_id = adv.get("id") if isinstance(adv.get("id"), str) and AR_RE.match(adv.get("id")) else None
    return {"creative_id": raw["id"], "advertiser_id": adv_id, "advertiser_name": _s(adv.get("name"), 150), "target_domain": _s(raw.get("target_domain"), 100),
            "format": _s(raw.get("format"), 20), "first_shown": _s(raw.get("first_shown_datetime"), 40), "last_shown": _s(raw.get("last_shown_datetime"), 40),
            "total_days_shown": _int(raw.get("total_days_shown"))}


def normalise_details(body):
    """Extract validated YouTube video IDs and creative text from an Ad Details response.

    A video ID is accepted from `video_id` or from `video_link`. If a single variation gives two different IDs, neither is trusted.
    """
    info = body.get("ad_information") if isinstance(body.get("ad_information"), dict) else {}
    variations = body.get("variations") if isinstance(body.get("variations"), list) else []
    videos, seen, text, conflicts = [], set(), [], 0
    for var in variations:
        if not isinstance(var, dict):
            continue
        ids = []
        vid = var.get("video_id")
        if isinstance(vid, str) and D.YT_ID.match(vid):
            ids.append(vid)
        link = var.get("video_link")
        if isinstance(link, str):
            p = D.parse_youtube_url(link)
            if p["ok"]:
                ids.append(p["video_id"])
        if len(set(ids)) > 1:
            conflicts += 1
            ids = []
        for i in set(ids):
            if i not in seen:
                seen.add(i); videos.append({"video_id": i, "channel": _s(var.get("channel"), 100), "duration": _s(var.get("duration"), 12)})
        t = {k: _s(var.get(k), 300) for k in ("title", "long_headline", "description")}
        if any(t.values()):
            text.append(t)
    regions = []
    for r in (info.get("regions") if isinstance(info.get("regions"), list) else [])[:60]:
        if isinstance(r, dict) and _s(r.get("code"), 8):
            regions.append({"code": _s(r.get("code"), 8), "name": _s(r.get("name"), 60), "first_shown": _s(r.get("first_shown_date"), 12), "last_shown": _s(r.get("last_shown_date"), 12)})
    meta = body.get("search_metadata") if isinstance(body.get("search_metadata"), dict) else {}
    return {"format": _s(info.get("format"), 20), "topic": _s(info.get("topic"), 80), "first_shown_date": _s(info.get("first_shown_date"), 12),
            "last_shown_date": _s(info.get("last_shown_date"), 12), "regions": regions, "videos": videos, "text_variants": text[:20],
            "conflicting_video_ids": conflicts, "provider_search_id": _s(meta.get("id"), 60)}


# ---------------------------------------------------------------- provider
class SearchApiProvider:
    name, label = PROVIDER, PROVIDER_LABEL

    def __init__(self, api_key=None, http_get=None):
        self.api_key = api_key if api_key is not None else os.environ.get(ENV_KEY, "")
        self.http_get = http_get or default_http_get

    @property
    def configured(self):
        k = (self.api_key or "").strip()
        return bool(k) and not k.lower().startswith(("your_", "paste", "changeme", "xxx", "<"))

    def _call(self, engine, params):
        if not self.configured:
            raise MissingKeyError(f"Transparency Center lookups are switched off because {ENV_KEY} is not set. Add it to your .env file to enable them.")
        q = {"engine": engine, **{k: v for k, v in params.items() if v not in (None, "")}}
        status, body = self.http_get(BASE_URL, q, {"Authorization": "Bearer " + self.api_key.strip()})
        self._raise_for(status, body)
        if not isinstance(body, dict):
            raise MalformedResponseError("SearchApi returned an unexpected response shape.")
        if body.get("error"):
            raise ProviderError("SearchApi reported an error: " + self._msg(body))
        return body

    def _msg(self, body):
        e = (body or {}).get("error") if isinstance(body, dict) else None
        m = e.get("message") if isinstance(e, dict) else e
        m = str(m or "")[:200]
        return m.replace(self.api_key, "***") if self.api_key else m

    def _raise_for(self, status, body):
        if status == 200:
            return
        m = self._msg(body)
        if status in (401, 403):
            raise InvalidKeyError(f"SearchApi rejected the API key (HTTP {status}). Check {ENV_KEY} in your .env file.")
        if status == 402:
            raise QuotaError("SearchApi reports no remaining credits on this plan (HTTP 402). Add credits or upgrade, then retry.")
        if status == 429:
            raise RateLimitError("SearchApi is rate limiting requests (HTTP 429). Wait a minute and retry.")
        if status >= 500:
            raise ProviderError(f"SearchApi had a temporary problem (HTTP {status}). Try again shortly.")
        raise ProviderError(f"SearchApi rejected the request (HTTP {status}). {m}".strip())

    def search_advertisers(self, q, region="ANYWHERE"):
        body = self._call("google_ads_transparency_center_advertiser_search", {"q": q, "region": None if region == "ANYWHERE" else region, "num_advertisers": 10, "num_domains": 5})
        advs = [a for a in (normalise_advertiser(x) for x in (body.get("advertisers") if isinstance(body.get("advertisers"), list) else [])) if a]
        doms = [d.get("name") for d in (body.get("domains") if isinstance(body.get("domains"), list) else []) if isinstance(d, dict) and _s(d.get("name"), 100)]
        return {"advertisers": advs, "domains": doms[:5]}

    def list_creatives(self, advertiser_id=None, domain=None, region="ANYWHERE", num=LIST_PAGE_SIZE):
        body = self._call("google_ads_transparency_center", {"advertiser_id": advertiser_id, "domain": None if advertiser_id else domain,
                          "region": None if region == "ANYWHERE" else region, "platform": "youtube", "ad_format": "video", "num": num})
        raw = body.get("ad_creatives") if isinstance(body.get("ad_creatives"), list) else []
        creatives = [c for c in (normalise_creative(x) for x in raw) if c]
        total = _int((body.get("search_information") or {}).get("total_results")) if isinstance(body.get("search_information"), dict) else None
        more = bool(isinstance(body.get("pagination"), dict) and body["pagination"].get("next_page_token"))
        return {"creatives": creatives, "total_reported": total, "has_more": more, "malformed_rows": len(raw) - len(creatives)}

    def creative_details(self, advertiser_id, creative_id):
        return normalise_details(self._call("google_ads_transparency_center_ad_details", {"advertiser_id": advertiser_id, "creative_id": creative_id}))


# ---------------------------------------------------------------- usage counter (local estimate of provider requests this month)
class UsageCounter:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def month():
        return time.strftime("%Y-%m", time.gmtime())

    def _read(self):
        try:
            d = json.loads(self.path.read_text())
            return d if d.get("month") == self.month() else {"month": self.month(), "requests": 0}
        except Exception:
            return {"month": self.month(), "requests": 0}

    def add(self, n=1):
        d = self._read(); d["requests"] += int(n)
        try: self.path.write_text(json.dumps(d))
        except OSError: pass
        return d["requests"]

    def snapshot(self):
        return {"requests_this_month": self._read()["requests"],
                "note": "AdPilot's own count of provider requests this calendar month (UTC), cache hits excluded. Your SearchApi dashboard is authoritative."}


# ---------------------------------------------------------------- name matching (used ONLY to choose which advertiser to inspect, never to verify)
_CORP = {"inc", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "company", "gmbh", "pvt", "private", "sa", "ag", "the", "official", "channel", "tv"}


def _name_tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _CORP}


def name_score(a, b):
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    if ta <= tb or tb <= ta:
        return 0.9
    return len(ta & tb) / len(ta | tb)


def _text_overlap(a, b):
    ta, tb = set(re.findall(r"[a-z0-9]+", (a or "").lower())), set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    ta, tb = {t for t in ta if len(t) > 2}, {t for t in tb if len(t) > 2}
    return (len(ta & tb) / len(ta | tb), len(ta & tb)) if ta and tb else (0.0, 0)


def parse_hints(hints):
    """User-supplied advertiser hints: 'AR...' id, a domain, or a name. At most 6, validated and de-duplicated."""
    out, seen = [], set()
    for h in hints or []:
        h = (h or "").strip()[:120] if isinstance(h, str) else ""
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        if AR_RE.match(h.upper()):
            out.append({"kind": "id", "value": h.upper()})
        elif DOMAIN_RE.match(h.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")):
            out.append({"kind": "domain", "value": h.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")})
        elif re.search(r"[A-Za-z0-9]", h):
            out.append({"kind": "name", "value": h})
    return out[:6]


# ---------------------------------------------------------------- orchestration
class TransparencyService:
    """Searches advertiser records, inspects a bounded number of creatives, and matches them to discovered videos."""

    def __init__(self, provider, cache, usage=None):
        self.provider, self.cache, self.usage = provider, cache, usage

    @property
    def configured(self):
        return bool(getattr(self.provider, "configured", False))

    def status(self):
        return {"provider": self.provider.name, "provider_label": getattr(self.provider, "label", self.provider.name), "configured": self.configured, "env_var": ENV_KEY,
                "cache_ttl_seconds": self.cache.ttl, "defaults": {"max_creative_details": DEFAULT_MAX_DETAILS, "max_advertisers": DEFAULT_MAX_ADVERTISERS},
                "usage": self.usage.snapshot() if self.usage else None,
                "cost_note": "Each uncached lookup uses provider credits: 1 per advertiser search, 1 per advertiser creative list, 1 per creative inspected. Repeat runs are served from saved results until you choose Refresh."}

    # --- cached provider call
    def _fetch(self, st, key, fn, refresh):
        if not refresh:
            hit = self.cache.get(key)
            if hit:
                st["cache_hits"] += 1
                return hit["data"], hit["fetched_at"]
        data = fn()
        st["requests"] += 1
        if self.usage: self.usage.add(1)
        return data, self.cache.set(key, {"data": data})["fetched_at"]

    def verify(self, videos, hints=None, region="ANYWHERE", refresh=False, max_advertisers=DEFAULT_MAX_ADVERTISERS, max_details=DEFAULT_MAX_DETAILS):
        region = normalise_region(region)
        max_advertisers = max(1, min(int(max_advertisers or DEFAULT_MAX_ADVERTISERS), MAX_ADVERTISERS_CAP))
        max_details = max(1, min(int(max_details or DEFAULT_MAX_DETAILS), MAX_DETAILS_CAP))
        now = time.time()
        st = {"requests": 0, "cache_hits": 0}
        clean = [v for v in (videos or []) if isinstance(v, dict)]
        result = {"provider": self.provider.name, "provider_label": PROVIDER_LABEL, "region": region, "checked_at": now, "results": {}, "advertisers": [], "errors": [],
                  "limits": {"max_advertisers": max_advertisers, "max_creative_details": max_details}}
        manual_url = transparency_url(region=region)
        targets_vids = [v for v in clean if isinstance(v.get("video_id"), str) and D.YT_ID.match(v["video_id"])]
        for v in clean:
            if v not in targets_vids:
                result["results"][str(v.get("video_id"))] = self._v("not_checked", "This entry has no real YouTube video ID (it was typed in by hand), so it cannot be matched automatically.", None, manual_url, now)
        if not self.configured:
            msg = f"Transparency Center lookups are off because {ENV_KEY} is not set."
            for v in targets_vids:
                result["results"][v["video_id"]] = self._v("not_checked", msg + " You can still check manually and record a source.", None, manual_url, now)
            result.update(available=False, code="missing_key", message=msg + " Everything else in AdPilot still works.", **st)
            return result
        wanted = {v["video_id"] for v in targets_vids}
        if not wanted:
            result.update(available=True, message="No discovered videos with a YouTube ID to check.", **st)
            return result

        # 1. which advertisers to inspect: user hints first, then the channels of the most relevant discovered videos
        targets = parse_hints(hints)
        by_channel = {}
        for v in sorted(targets_vids, key=lambda x: -(x.get("relevance") or 0)):
            ch = _s(v.get("channel_title"), 120)
            if ch and not any(name_score(ch, t["value"]) >= 0.9 for t in targets if t["kind"] == "name") and ch.lower() not in by_channel:
                by_channel[ch.lower()] = {"kind": "name", "value": ch, "from_channel": True}
        targets = (targets + list(by_channel.values()))[:max_advertisers]
        records, interrupted, details_used = [], None, 0

        def stop(e):
            nonlocal interrupted
            interrupted = e
            result["errors"].append({"code": e.code, "message": str(e)})

        for t in targets:
            if interrupted:
                break
            info = {"query": t["value"], "kind": t["kind"], "matched": None, "creatives_listed": 0, "creatives_reported": None, "details_checked": 0, "more_creatives_not_listed": False, "note": None}
            result["advertisers"].append(info)
            try:
                adv_id, domain = None, None
                if t["kind"] == "id":
                    adv_id = t["value"]; info["matched"] = {"advertiser_id": adv_id, "name": None, "score": None}
                elif t["kind"] == "domain":
                    domain = t["value"]; info["matched"] = {"domain": domain}
                else:
                    found, _ = self._fetch(st, f"adv|{region}|{t['value'].lower()}", lambda: self.provider.search_advertisers(t["value"], region), refresh)
                    scored = sorted(((name_score(t["value"], a["name"]), a.get("ads_upper") or 0, a) for a in found["advertisers"]), key=lambda x: (-x[0], -x[1]))
                    if not scored or scored[0][0] < NAME_MATCH_MIN:
                        info["note"] = "No advertiser name was close enough to this name. Add the advertiser's website domain or its AR… ID to search directly."
                        continue
                    sc, _, best = scored[0]
                    adv_id = best["advertiser_id"]
                    info["matched"] = {"advertiser_id": adv_id, "name": best["name"], "score": round(sc, 2), "other_candidates": [a["name"] for _, _, a in scored[1:4] if a["name"]]}
                listing, ts = self._fetch(st, f"list|{region}|{adv_id or domain}", lambda: self.provider.list_creatives(adv_id, domain, region), refresh)
                creatives = sorted(listing["creatives"], key=lambda c: c.get("last_shown") or "", reverse=True)
                info.update(creatives_listed=len(creatives), creatives_reported=listing.get("total_reported"), more_creatives_not_listed=bool(listing.get("has_more")))
                for c in creatives:
                    if (wanted <= {vid for r in records for vid in r["video_ids"]}) or details_used >= max_details:
                        break
                    aid = c["advertiser_id"] or adv_id
                    if not aid:
                        continue
                    det, dts = self._fetch(st, f"det|{aid}|{c['creative_id']}", lambda: self.provider.creative_details(aid, c["creative_id"]), refresh)
                    details_used += 1; info["details_checked"] += 1
                    records.append({"creative": {**c, "advertiser_id": aid}, "details": det, "video_ids": {x["video_id"] for x in det["videos"]}, "retrieved_at": dts,
                                    "advertiser_name": c["advertiser_name"] or (info["matched"] or {}).get("name")})
            except TransparencyError as e:
                # SearchApi sometimes returns this parser-specific error for one
                # advertiser query even when the API key and other engines work.
                # Treat it as a failed candidate, not a failure of the whole run:
                # continue checking other advertiser hints. Authentication, quota,
                # rate-limit, network, and other provider errors still stop the run.
                if (isinstance(e, ProviderError) and
                        "parser didn't return any results" in str(e).lower() and
                        t["kind"] == "name"):
                    info["note"] = (
                        "SearchApi could not parse results for this advertiser-name query. "
                        "Try the official advertiser name, website domain, or AR… ID."
                    )
                    result["errors"].append({
                        "code": "advertiser_search_no_results",
                        "message": f"Advertiser search failed for {t['value']}: {e}"
                    })
                    continue
                stop(e)
        result["requests_made"], result["cache_hits"] = st["requests"], st["cache_hits"]
        result["creatives_inspected"] = details_used

        # 2. match each discovered video against the retrieved records
        for v in targets_vids:
            result["results"][v["video_id"]] = self._match(v, records, result["advertisers"], interrupted, region, now, details_used >= max_details)
        n_exact = sum(1 for r in result["results"].values() if r["state"] == "verified_exact")
        result.update(available=True, interrupted=bool(interrupted), exact_matches=n_exact)
        result["message"] = (f"{n_exact} exact video-ID match(es) found among {details_used} creative(s) inspected." if not interrupted else
                             f"The check was interrupted: {interrupted}. {n_exact} exact match(es) were found before that.")
        if interrupted and interrupted.code in ("missing_key",):
            result["available"] = False
        return result

    # --- build one verification record
    @staticmethod
    def _v(state, reason, record, manual_url, now, coverage=None, evidence=None, method=None, retrieved_at=None):
        return {"state": state, "label": STATE_LABEL[state], "reason": reason, "method": method, "source": PROVIDER, "source_label": PROVIDER_LABEL,
                "checked_at": now, "retrieved_at": retrieved_at, "record": record, "coverage": coverage, "evidence": evidence or [], "manual_review_url": manual_url}

    def _match(self, video, records, advertisers, interrupted, region, now, budget_hit):
        vid, manual_url = video["video_id"], transparency_url(region=region)
        cover = {"advertisers": [{"query": a["query"], "matched_name": (a.get("matched") or {}).get("name"), "creatives_listed": a["creatives_listed"], "creatives_reported": a["creatives_reported"],
                                  "details_checked": a["details_checked"]} for a in advertisers], "creatives_inspected": sum(a["details_checked"] for a in advertisers)}
        # EXACT: provider-supplied video ID equals this video's ID
        hits = [r for r in records if vid in r["video_ids"]]
        if hits:
            r = hits[0]; c, d = r["creative"], r["details"]
            reg = ", ".join(x["code"] for x in d["regions"][:8]) or "not listed"
            ev = [f"The provider returned YouTube video ID {vid} inside Transparency Center creative {c['creative_id']} of advertiser {r['advertiser_name'] or c['advertiser_id']} ({c['advertiser_id']}).",
                  f"First shown {c.get('first_shown') or d.get('first_shown_date') or 'unknown'}, last shown {c.get('last_shown') or d.get('last_shown_date') or 'unknown'}, total days shown {c.get('total_days_shown') if c.get('total_days_shown') is not None else 'unknown'}. Regions listed: {reg}.",
                  f"Source: {PROVIDER_LABEL}, retrieved {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(r['retrieved_at']))}. The same record can be opened on Google's own site with the evidence link."]
            rec = {"creative_id": c["creative_id"], "advertiser_id": c["advertiser_id"], "advertiser_name": r["advertiser_name"], "format": c.get("format") or d.get("format"),
                   "first_shown": c.get("first_shown"), "last_shown": c.get("last_shown"), "total_days_shown": c.get("total_days_shown"), "regions": d["regions"][:8],
                   "matched_video_id": vid, "search_region": region, "provider_search_id": d.get("provider_search_id"), "other_matching_creatives": [x["creative"]["creative_id"] for x in hits[1:6]],
                   "evidence_url": transparency_url(c["advertiser_id"], c["creative_id"], region)}
            return self._v("verified_exact", "Exact match: the Transparency Center record contains this video's YouTube ID, so this video was part of a paid ad creative shown by that advertiser.",
                           rec, manual_url, now, cover, ev, "video_id_exact", r["retrieved_at"])
        # POSSIBLE: same advertiser name and similar creative text, but no ID match. Supporting evidence only.
        ch, title = video.get("channel_title") or "", video.get("title") or ""
        for r in records:
            if name_score(ch, r["advertiser_name"] or "") < NAME_MATCH_MIN:
                continue
            for tv in r["details"]["text_variants"]:
                j, shared = _text_overlap(title, " ".join(x for x in (tv.get("title"), tv.get("long_headline")) if x))
                if j >= 0.6 and shared >= 3:
                    c = r["creative"]
                    return self._v("possible_match", "Not verified. The advertiser name resembles this channel and the ad text resembles this video's title, but the record does not contain this video's ID, so it may be a different creative.",
                                   {"creative_id": c["creative_id"], "advertiser_id": c["advertiser_id"], "advertiser_name": r["advertiser_name"], "matched_video_id": None, "search_region": region,
                                    "evidence_url": transparency_url(c["advertiser_id"], c["creative_id"], region)}, manual_url, now, cover,
                                   [f"Text similarity {j:.2f} between the video title and an ad variation of creative {c['creative_id']}. Text similarity alone never verifies a video."], "metadata_supporting", r["retrieved_at"])
        # UNVERIFIED / NOT CHECKED
        if interrupted:
            return self._v("not_checked", f"The Transparency Center check was interrupted before this video could be matched: {interrupted}", None, manual_url, now, cover)
        if not advertisers:
            return self._v("unverified", "No advertiser was searched. Add an advertiser name, domain or AR… ID.", None, manual_url, now, cover)
        matched = [a for a in advertisers if a.get("matched")]
        if not matched:
            return self._v("unverified", "No Transparency Center advertiser matched this video's channel or your hints, so nothing could be compared. Add the advertiser's website domain or AR… ID, or review manually.", None, manual_url, now, cover)
        partial = budget_hit or any(a["more_creatives_not_listed"] or (a["creatives_reported"] or 0) > a["creatives_listed"] or a["details_checked"] < a["creatives_listed"] for a in matched)
        names = ", ".join(sorted({(a["matched"].get("name") or a["matched"].get("domain") or a["matched"].get("advertiser_id") or a["query"]) for a in matched}))[:200]
        why = (f"{cover['creatives_inspected']} YouTube video creative(s) of {names} were inspected and none contained this video's ID. "
               + ("Coverage was partial (not every creative was inspected), so this video could still be an ad. " if partial else "")
               + "This is not proof the video was never advertised.")
        return self._v("unverified", why, None, manual_url, now, cover)


# ---------------------------------------------------------------- sanitising + classification overlay
def sanitize_verification(v):
    """Allow-list a verification object that came back from the browser before it is stored in a report or rendered."""
    if not isinstance(v, dict) or v.get("state") not in STATES:
        return None
    rec = v.get("record") if isinstance(v.get("record"), dict) else None
    out = {"state": v["state"], "label": STATE_LABEL[v["state"]], "reason": _s(v.get("reason"), 600) or "", "method": _s(v.get("method"), 40), "source": _s(v.get("source"), 30),
           "source_label": _s(v.get("source_label"), 80), "checked_at": v.get("checked_at") if isinstance(v.get("checked_at"), (int, float)) else None,
           "retrieved_at": v.get("retrieved_at") if isinstance(v.get("retrieved_at"), (int, float)) else None,
           "evidence": [e[:400] for e in (v.get("evidence") or []) if isinstance(e, str)][:6], "manual_review_url": safe_transparency_url(v.get("manual_review_url"))}
    out["record"] = None if rec is None else {
        "creative_id": rec.get("creative_id") if isinstance(rec.get("creative_id"), str) and CR_RE.match(rec["creative_id"]) else None,
        "advertiser_id": rec.get("advertiser_id") if isinstance(rec.get("advertiser_id"), str) and AR_RE.match(rec["advertiser_id"]) else None,
        "advertiser_name": _s(rec.get("advertiser_name"), 150), "matched_video_id": rec.get("matched_video_id") if isinstance(rec.get("matched_video_id"), str) and D.YT_ID.match(rec["matched_video_id"]) else None,
        "first_shown": _s(rec.get("first_shown"), 40), "last_shown": _s(rec.get("last_shown"), 40), "total_days_shown": _int(rec.get("total_days_shown")),
        "search_region": _s(rec.get("search_region"), 8), "evidence_url": safe_transparency_url(rec.get("evidence_url"))}
    return out


def classify_with_verification(video, ctx, manual=None, verification=None):
    """Existing classification plus the Transparency Center verification. Exact ID match is the only automated route to 'Verified Paid Ad'.

    A user's manual confirmation is kept distinct: method 'manual' vs 'transparency_video_id' (or both).
    """
    base = D.classify_video(video, ctx, manual)
    t = sanitize_verification(verification)
    out = {**base, "verification": t}
    if not t:
        return out
    rec = t["record"] or {}
    if t["state"] == "verified_exact" and rec.get("matched_video_id") and rec["matched_video_id"] == video.get("video_id"):
        manual_too = base.get("verification_method") == "manual"
        out.update(status=D.STATUS_VERIFIED, evidence=t["evidence"] + (base["evidence"] if manual_too else []),
                   verification_method="transparency_video_id+manual" if manual_too else "transparency_video_id",
                   verification_note="Automated: an exact YouTube video-ID match in Google Ads Transparency Center data supplied by SearchApi." + (" You also confirmed it manually." if manual_too else "")
                   + " This shows the video was part of a paid ad creative. It says nothing about the ad's spend or performance.",
                   transparency_url=rec.get("evidence_url") or D.TRANSPARENCY_URL)
    else:
        out["evidence"] = base["evidence"] + [f"Transparency Center check: {t['label']}. {t['reason']}"]
        if t["state"] != "possible_match" and base.get("verification_method") != "manual":
            out["verification_note"] = base["verification_note"] + f" Transparency Center check: {t['label'].lower()}."
        if t["state"] == "possible_match":
            out["verification_note"] = base["verification_note"] + " A possible Transparency Center match exists but is not verified."
        if t.get("manual_review_url") and base.get("verification_method") != "manual":
            out["transparency_url"] = (rec.get("evidence_url") or t["manual_review_url"])
    return out


def summarise(analyses):
    """Counts used by the report: verified (automated), user-confirmed, possible, unverified, not checked, and reference-only."""
    s = {"verified_automated": 0, "user_confirmed": 0, "possible_match": 0, "unverified": 0, "not_checked": 0, "reference_only": 0, "total": 0}
    for a in analyses:
        if a.get("expired"):
            continue
        s["total"] += 1
        t, basis = a.get("verification"), a.get("verification_basis")
        if basis == "transparency_exact":
            s["verified_automated"] += 1; continue
        if basis == "user_confirmed":
            s["user_confirmed"] += 1; continue
        s["reference_only"] += 1
        st = (t or {}).get("state")
        s[{"possible_match": "possible_match", "unverified": "unverified"}.get(st, "not_checked")] += 1
    return s
