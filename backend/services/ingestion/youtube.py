"""YouTube ingestion: turn a video link into a timestamped transcript note the normal pipeline can learn from.

Order of attempts:
1. **Captions** via ``youtube-transcript-api`` (MIT): the uploader's English track, else YouTube's
   auto-generated English, else any track (translated to English when YouTube offers it). Free and
   fast (~2 s), but YouTube blocks many cloud IPs, so production can hit ``RequestBlocked``.
2. **Gemini video understanding**: Gemini accepts a public YouTube URL as ``file_data`` and fetches it
   from Google's side, so it works where captions are blocked or missing. Costs tokens (low media
   resolution keeps it near 100 tokens per second of video), so it only runs when step 1 fails.
3. If both fail the caller stores the link alone and says so; nothing pretends to have been read.

Title and channel come from YouTube's oEmbed endpoint, which needs no API key.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
import structlog

logger = structlog.get_logger()

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com",
          "www.youtube-nocookie.com"}
_NOISE = re.compile(r"\[(?:music|applause|laughter|silence|inaudible|__)\]|♪+", re.I)
PARAGRAPH_SECONDS = 60
GEMINI_TIMEOUT_S = float(os.getenv("YOUTUBE_GEMINI_TIMEOUT_S", "240"))

_GEMINI_PROMPT = """Transcribe this video's speech as faithfully as you can, in English.
Group it into paragraphs of roughly one minute and start each paragraph with its start time as [mm:ss]
(or [h:mm:ss] past an hour). Where something important is shown but not said (an equation, a diagram,
code, a slide title), add it in square brackets, e.g. [On screen: softmax(x)_i = e^x_i / sum_j e^x_j].
Do not summarize, add commentary or a title. Output only the transcript."""


class YouTubeError(Exception):
    """A link that is not a YouTube video we can identify."""


@dataclass
class VideoTranscript:
    video_id: str
    url: str
    title: Optional[str] = None
    channel: Optional[str] = None
    text: str = ""  # markdown body with [mm:ss] paragraph markers
    source: str = "none"  # "captions" | "auto_captions" | "gemini" | "none"
    language: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.text.strip()) >= 80


def parse_video_id(url: str) -> str:
    """watch?v=, youtu.be/, /shorts/, /embed/, /live/, /v/ (with or without scheme). Raises YouTubeError."""
    raw = (url or "").strip()
    if _ID.match(raw):
        return raw
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    host = (p.hostname or "").lower()
    parts = [s for s in p.path.split("/") if s]
    vid: Optional[str] = None
    if host in ("youtu.be", "www.youtu.be"):
        vid = parts[0] if parts else None
    elif host in _HOSTS:
        if p.path.rstrip("/") in ("/watch", ""):
            vid = (parse_qs(p.query).get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v", "e"):
            vid = parts[1]
    if not vid or not _ID.match(vid):
        raise YouTubeError("That doesn't look like a YouTube video link.")
    return vid


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"[{h}:{m:02d}:{sec:02d}]" if h else f"[{m:02d}:{sec:02d}]"


def paragraphs_from_snippets(snippets: list[tuple[float, str]], every: int = PARAGRAPH_SECONDS) -> str:
    """Caption snippets are 2-5 s fragments; join them into ~1 minute paragraphs, each with its start time."""
    out: list[str] = []
    cur: list[str] = []
    start: Optional[float] = None
    for t, text in snippets:
        text = _NOISE.sub(" ", text.replace("\n", " ")).strip()
        if not text:
            continue
        if start is None:
            start = t
        elif t - start >= every and cur:
            out.append(f"{stamp(start)} {' '.join(cur)}")
            cur, start = [], t
        cur.append(text)
    if cur and start is not None:
        out.append(f"{stamp(start)} {' '.join(cur)}")
    return "\n\n".join(re.sub(r"\s{2,}", " ", p) for p in out)


async def fetch_metadata(video_id: str, client: Optional[httpx.AsyncClient] = None) -> dict:
    """Title, channel and thumbnail from oEmbed. Empty dict on any failure (private or removed videos 4xx)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        r = await client.get("https://www.youtube.com/oembed", params={"url": watch_url(video_id), "format": "json"})
        if r.status_code != 200:
            return {}
        d = r.json()
        return {"title": d.get("title"), "channel": d.get("author_name"), "thumbnail": d.get("thumbnail_url")}
    except Exception as e:  # metadata is a nicety; never fail the import on it
        logger.info("youtube: oembed failed", video_id=video_id, error=str(e))
        return {}
    finally:
        if own:
            await client.aclose()


def _fetch_captions_sync(video_id: str) -> tuple[list[tuple[float, str]], str, bool]:
    """Returns (snippets, language_code, is_generated). Raises the library's exceptions."""
    from youtube_transcript_api import YouTubeTranscriptApi

    listing = YouTubeTranscriptApi().list(video_id)
    english = ["en", "en-US", "en-GB", "en-CA", "en-AU", "en-IN"]
    tr = None
    for finder in (listing.find_manually_created_transcript, listing.find_generated_transcript):
        try:
            tr = finder(english)
            break
        except Exception:
            continue
    if tr is None:
        tr = next(iter(listing))  # any language; translate when YouTube can
        if tr.is_translatable and any(t.language_code == "en" for t in tr.translation_languages):
            tr = tr.translate("en")
    fetched = tr.fetch()
    return [(s.start, s.text) for s in fetched.snippets], fetched.language_code, fetched.is_generated


async def fetch_captions(video_id: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(markdown, source, language, failure_reason). The library is synchronous, so it runs in a thread."""
    try:
        snippets, lang, generated = await asyncio.wait_for(asyncio.to_thread(_fetch_captions_sync, video_id), 30)
    except Exception as e:
        reason = type(e).__name__
        logger.info("youtube: captions unavailable", video_id=video_id, reason=reason)
        return None, None, None, reason
    text = paragraphs_from_snippets(snippets)
    return text, ("auto_captions" if generated else "captions"), lang, None


async def transcribe_with_gemini(video_id: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Gemini watches the video (by URL) and returns a timestamped transcript. None when it can't."""
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key or os.getenv("YOUTUBE_GEMINI_FALLBACK", "1") == "0":
        return None
    from backend.config.llm import DEFAULT_CHAT_MODEL

    model = os.getenv("YOUTUBE_GEMINI_MODEL", DEFAULT_CHAT_MODEL)
    body = {
        "contents": [{"parts": [{"file_data": {"file_uri": watch_url(video_id)}}, {"text": _GEMINI_PROMPT}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 32768, "mediaResolution": "MEDIA_RESOLUTION_LOW"},
    }
    own = client is None
    client = client or httpx.AsyncClient(timeout=GEMINI_TIMEOUT_S)
    try:
        r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              json=body, headers={"x-goog-api-key": key})
        if r.status_code != 200:
            logger.warning("youtube: gemini fallback failed", video_id=video_id, status=r.status_code,
                           detail=r.text[:300])
            return None
        data = r.json()
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        usage = data.get("usageMetadata") or {}
        logger.info("youtube: gemini transcript", video_id=video_id, chars=len(text),
                    prompt_tokens=usage.get("promptTokenCount"), output_tokens=usage.get("candidatesTokenCount"))
        return text or None
    except Exception as e:
        logger.warning("youtube: gemini fallback error", video_id=video_id, error=str(e))
        return None
    finally:
        if own:
            await client.aclose()


async def get_transcript(url: str) -> VideoTranscript:
    """Captions first, Gemini second. Raises YouTubeError only for links that aren't YouTube videos."""
    vid = parse_video_id(url)
    meta, (text, source, lang, reason) = await asyncio.gather(fetch_metadata(vid), fetch_captions(vid))
    v = VideoTranscript(video_id=vid, url=watch_url(vid), title=meta.get("title"), channel=meta.get("channel"))
    if text and len(text.strip()) >= 80:
        v.text, v.source, v.language = text, source or "captions", lang
        if lang and not lang.startswith("en"):
            v.warnings.append(f"transcript is in '{lang}': no English captions were available")
        return v
    gem = await transcribe_with_gemini(vid)
    if gem and len(gem.strip()) >= 80:
        v.text, v.source = gem, "gemini"
        v.warnings.append("no usable captions" + (f" ({reason})" if reason else "") +
                          ": transcribed by Gemini from the video, so wording may differ from the speaker's")
        return v
    v.warnings.append("couldn't get a transcript" + (f" ({reason})" if reason else "") +
                      ": saved the link only, so nothing from this video is in your graph yet")
    return v


def render_note(v: VideoTranscript) -> str:
    head = [f"# {v.title or 'YouTube video'}", ""]
    meta = [f"Video: {v.url}"]
    if v.channel:
        meta.append(f"Channel: {v.channel}")
    meta.append({"captions": "Transcript: the uploader's captions",
                 "auto_captions": "Transcript: YouTube's automatic captions",
                 "gemini": "Transcript: transcribed by Gemini from the video"}.get(v.source, "Transcript: none"))
    return "\n".join(head + meta + ["", "## Transcript", "", v.text.strip()]) + "\n"
