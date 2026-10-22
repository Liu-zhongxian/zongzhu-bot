"""Song search on a local go-music-dl web service: NetEase first, other platforms only when it lacks the original.

go-music-dl has no documented API; these endpoints come from its web page (v1.1.3):
/search returns HTML whose song cards carry data-* attributes, /inspect reports
whether a song is playable, /download?...&stream=1 relays the audio, /lyric gives LRC.

Picking rules (tested against live results, 2026-10-22):
- With a singer ("周杰伦的晴天"): NetEase alone first; without a match there, the
  fallback platforms are searched together.
- Title only ("晴天"): every platform's top original votes for its singer (each
  platform carries the original, covers differ), and the most voted singer wins;
  NetEase's copy is used when it has one.
- Live, cover, remix, "...版" titles and albums of that kind are not the original,
  nor are look-alike uploaders ("周杰伦.", "HF薛之谦").
- Among playable candidates of the same standing the highest bitrate wins: Kuwo
  often serves 128 kbps where Migu has 900+.
"""

import html
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

try:
    from pypinyin import lazy_pinyin
except ImportError:  # optional: without it a misheard title is simply not found
    lazy_pinyin = None

PRIMARY = "netease"
FALLBACK = ("qq", "kugou", "kuwo", "migu")
TIMEOUT = 15

VARIANT = re.compile(
    r"live|现场|演唱会|翻唱|翻自|cover|原唱|伴奏|纯音乐|instrumental|karaoke|dj|remix|混音|"
    r"钢琴|吉他|八音盒|女声|男声|深情|史诗|史詩|抖音|片段|铃声|慢速|加速|0\.8x|1\.2x|beat|demo|试听|小样|伴唱|版|"
    r"r&b|变速|环绕|3d|8d|特辑|新歌声|蒙面|好声音",
    re.I,
)
ALBUM_VARIANT = re.compile(r"live|现场|演唱会|remix|混音|dj|电音|翻唱|伴奏|纯音乐|好声音|新歌声|蒙面", re.I)
BRACKETS = re.compile(r"[(（\[【].*?[)）\]】]")
SEPARATORS = re.compile(r"[、,，/&;；]| feat\. | ft\. ")
CARD = re.compile(r'<[a-z]+[^>]*class="song-card[^"]*"[^>]*>')
ATTR = re.compile(r'data-([a-z_-]+)="([^"]*)"')


@dataclass(frozen=True)
class Song:
    id: str
    source: str
    name: str
    artist: str
    album: str = ""
    duration: str = ""
    extra: str = ""

    def query(self) -> str:
        params = {"id": self.id, "source": self.source, "name": self.name, "artist": self.artist,
                  "album": self.album, "duration": self.duration}
        if self.extra not in ("", "{}", "null"):
            params["extra"] = self.extra
        return urllib.parse.urlencode(params)

    @property
    def title(self) -> str:
        return f"{self.artist}的{self.name}" if self.artist else self.name


def _norm(text: str) -> str:
    return re.sub(r"[\s·・,，。.!！?？'\"“”‘’-]+", "", text or "").casefold()


def artist_is(token: str, artist: str) -> bool:
    """Same singer, allowing a Latin stage name with a dot or a space ("G.E.M.邓紫棋",
    "周杰伦 Jay Chou") but not look-alike uploads ("周杰伦.", "HF薛之谦")."""
    token, artist = token.strip(), artist.strip()
    if token.casefold() == artist.casefold():
        return True
    i = token.casefold().find(artist.casefold())
    if i < 0:
        return False
    before, after = token[:i], token[i + len(artist):]
    for part, gap in ((before, before[-1:]), (after, after[:1])):
        if part and not (re.fullmatch(r"[A-Za-z][A-Za-z.\s]*", part.strip()) and ("." in part or gap == " ")):
            return False
    return True


def is_original(song: Song, title: Optional[str], artist: Optional[str] = None) -> bool:
    if VARIANT.search(song.name):
        return False
    if title is not None and _norm(BRACKETS.sub("", song.name)) != _norm(title):
        return False
    if artist is None:
        return True
    return any(artist_is(token, artist) for token in SEPARATORS.split(song.artist))


INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x",
            "r", "z", "c", "s", "y", "w")
# Close-sounding initials and finals ASR swaps (zh/z, an/ang, in/ing...)
NEAR = {frozenset(p) for p in (("zh", "z"), ("ch", "c"), ("sh", "s"), ("n", "l"), ("f", "h"), ("an", "ang"),
                                ("en", "eng"), ("in", "ing"), ("ian", "iang"), ("uan", "uang"))}
SOUND_MATCH = 0.75


def _split(syllable: str):
    for ini in INITIALS:
        if syllable.startswith(ini):
            return ini, syllable[len(ini):]
    return "", syllable


def _syllable_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    (ia, fa), (ib, fb) = _split(a), _split(b)
    same_i = ia == ib or frozenset((ia, ib)) in NEAR
    same_f = fa == fb or frozenset((fa, fb)) in NEAR
    if same_i and same_f:
        return 0.9
    if same_i or same_f:
        return 0.6 if fa[:1] == fb[:1] or same_f else 0.5
    return 0.0


def sounds_like(heard: str, title: str) -> float:
    """0-1: how close two titles sound ("请帖" and "晴天" ≈ 0.8). 0 without pypinyin or for different lengths."""
    if lazy_pinyin is None:
        return 0.0
    a, b = lazy_pinyin(_norm(heard)), lazy_pinyin(_norm(BRACKETS.sub("", title)))
    if not a or len(a) != len(b):
        return 0.0
    return sum(_syllable_score(x, y) for x, y in zip(a, b)) / len(a)


def _tier(song: Song) -> Tuple[bool, bool, bool]:
    album = song.album.strip()
    return (bool(BRACKETS.search(song.name)), bool(SEPARATORS.search(song.artist)),
            album in ("", "NULL") or bool(ALBUM_VARIANT.search(album)))


class GoMusicDL:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def stream_url(self, song: Song) -> str:
        return f"{self.base}/download?{song.query()}&stream=1"

    def search(self, keyword: str, sources: Iterable[str]) -> List[Song]:
        params = [("q", keyword), ("type", "song"), ("page", "1"), ("page_size", "20")]
        params += [("sources", s) for s in sources]
        with urllib.request.urlopen(f"{self.base}/search?{urllib.parse.urlencode(params)}", timeout=TIMEOUT) as r:
            page = r.read().decode("utf-8", "replace")
        songs = []
        for card in CARD.findall(page):
            a = {k: html.unescape(v) for k, v in ATTR.findall(card)}
            if a.get("id") and a.get("source"):
                songs.append(Song(a["id"], a["source"], a.get("name", ""), a.get("artist", ""),
                                  a.get("album", ""), a.get("duration", ""), a.get("extra", "")))
        return songs

    def bitrate(self, song: Song) -> int:
        """kbps when playable (1 when unknown), 0 when not."""
        params = urllib.parse.urlencode({"id": song.id, "source": song.source, "duration": song.duration})
        try:
            with urllib.request.urlopen(f"{self.base}/inspect?{params}", timeout=TIMEOUT) as r:
                info = json.load(r)
        except (OSError, ValueError):
            return 0
        if not info.get("valid"):
            return 0
        m = re.search(r"\d+", str(info.get("bitrate") or ""))
        return int(m.group()) if m else 1

    def pick(self, candidates: List[Song], check: int = 6) -> Optional[Song]:
        """Best tier first, then the highest bitrate among a batch checked together."""
        order = (PRIMARY,) + FALLBACK
        ranked = sorted(candidates, key=lambda s: (_tier(s), order.index(s.source) if s.source in order else 99))
        while ranked:
            batch, ranked = ranked[:check], ranked[check:]
            with ThreadPoolExecutor(len(batch)) as pool:
                rates = list(pool.map(self.bitrate, batch))
            ok = [(_tier(s), -rate, i, s) for i, (s, rate) in enumerate(zip(batch, rates)) if rate]
            if ok:
                return min(ok)[3]
        return None

    def _each(self, keyword: str, sources: Iterable[str]) -> List[List[Song]]:
        sources = list(sources)
        with ThreadPoolExecutor(len(sources)) as pool:
            return list(pool.map(lambda src: self._safe_search(keyword, [src]), sources))

    def _safe_search(self, keyword: str, sources) -> List[Song]:
        try:
            return self.search(keyword, sources)
        except (OSError, ValueError):
            return []

    def find(self, title: str, artist: Optional[str] = None) -> Tuple[Optional[Song], str]:
        """(song or None, why) for a title, optionally with its singer."""
        if artist:
            keyword = f"{artist} {title}"
            # All platforms at once (NetEase alone first cost ~0.5s more when it lacks the song)
            primary, *rest = self._each(keyword, (PRIMARY,) + FALLBACK)
            song = self.pick([s for s in primary if is_original(s, title, artist)])
            if song:
                return song, "网易云有原唱"
            others = [s for songs in rest for s in songs if is_original(s, title, artist)]
            song = self.pick(others)
            if song:
                return song, f"网易云没有原唱，用 {song.source}"
            return self._sounds_like(title, artist)

        results = self._each(title, (PRIMARY,) + FALLBACK)
        votes = Counter()
        for songs in results:
            top = next((s for s in songs if is_original(s, title)), None)
            if top:
                votes[top.artist] += 1
        if not votes:
            # Singer and title run together ("周杰伦晴天"), or "的" heard as 在/得/地 ("周杰伦在晴天"):
            # a result whose singer plus title is the whole phrase
            whole = _norm(title)
            for s in (s for songs in results for s in songs):
                lead = SEPARATORS.split(s.artist)[0].strip()
                rest = whole[len(_norm(lead)):] if lead and whole.startswith(_norm(lead)) else None
                if rest is not None and re.sub(r"^[的在得地之]", "", rest) == _norm(BRACKETS.sub("", s.name)):
                    return self.find(BRACKETS.sub("", s.name).strip(), lead)
            return None, "没找到歌名一致的原版"
        singer, count = votes.most_common(1)[0]
        mine = [s for songs in results for s in songs if is_original(s, title) and s.artist == singer]
        song = self.pick([s for s in mine if s.source == PRIMARY]) or self.pick(
            [s for s in mine if s.source != PRIMARY])
        if not song:
            return None, f"判断原唱是 {singer}，但都不能播放"
        return song, f"判断原唱是 {singer}（{count} 个平台排第一），用 {song.source}"

    def _sounds_like(self, heard: str, artist: str) -> Tuple[Optional[Song], str]:
        """The title was probably misheard ("周杰伦的请帖"): the singer's song that sounds closest."""
        songs = [s for results in self._each(artist, (PRIMARY,) + FALLBACK) for s in results
                 if is_original(s, None, artist)]
        if not songs:
            return None, "各平台都没找到这位歌手"
        scored = sorted(((sounds_like(heard, s.name), s) for s in songs), key=lambda x: -x[0])
        best = scored[0][0]
        if best < SOUND_MATCH:
            return None, "找到了这位歌手，但没有读音相近的歌"
        title = BRACKETS.sub("", scored[0][1].name).strip()
        # Search again under the right title: NetEase first and the best bitrate, as for any request
        song, _ = self.find(title, artist) if _norm(title) != _norm(heard) else (None, "")
        return song, (f"按读音改成 {song.name}" if song else "读音相近的歌都不能播放")

    def by_artist(self, artist: str, exclude: Iterable[str] = ()) -> Optional[Song]:
        """One original song by this singer whose title is not in `exclude` (for "下一首", "放周杰伦的歌")."""
        played = {_norm(BRACKETS.sub("", name)) for name in exclude}

        def fresh(songs):
            return [s for s in songs if is_original(s, None, artist) and _norm(BRACKETS.sub("", s.name)) not in played]

        # NetEase often has a singer only as a guest on others' songs (no 周杰伦 solo there): solo only
        solo = [s for s in fresh(self._safe_search(artist, [PRIMARY]))[:8] if not SEPARATORS.search(s.artist)]
        song = self.pick(solo)
        if song:
            return song
        others = [s for songs in self._each(artist, FALLBACK) for s in fresh(songs)[:8]]
        # pick() ranks solo, plainly titled songs first; check only that best tier
        best = min((_tier(s) for s in others), default=None)
        return self.pick([s for s in others if _tier(s) == best]) or self.pick(others)
