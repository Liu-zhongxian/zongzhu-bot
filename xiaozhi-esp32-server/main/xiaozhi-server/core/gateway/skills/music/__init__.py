"""Local music: songs through go-music-dl and mpv, transport and volume commands, on this Mac.

`command.py` holds the phrase rules and replies, `player.py` the programs, `source.py` the
song search. Config: `local_music` in .config.yaml (`enabled`, extra `hotwords`, ...).
"""
from core.gateway.skill import Skill

# Often requested singers: hotwords, and "周杰伦的晴天" said without a verb counts as a request
SINGERS = (
    "周杰伦", "林俊杰", "陈奕迅", "邓紫棋", "薛之谦", "毛不易", "李荣浩", "王菲", "张学友", "刘德华", "五月天",
    "蔡依林", "孙燕姿", "王力宏", "张惠妹", "华晨宇", "许嵩", "汪苏泷", "周深", "李健", "朴树", "赵雷", "陶喆",
    "莫文蔚", "张杰", "梁静茹", "邓丽君", "Beyond",
)
# Recognition hotwords while the skill is on: on the board "晴天" came out as "请帖" and
# "的" as "在" (2026-10-22). Singers and often requested songs, plus the commands.
HOTWORDS = [
    *SINGERS,
    "晴天", "七里香", "稻香", "青花瓷", "夜曲", "告白气球", "搁浅", "兰亭序", "简单爱", "江南", "孤勇者",
    "光年之外", "演员", "消愁", "富士山下", "十年", "后来", "小幸运", "起风了", "平凡之路", "成都", "南山南",
    "播放", "暂停", "继续播放", "下一首", "上一首", "切歌", "单曲循环", "快进", "快退", "音量", "静音",
]


class MusicSkill(Skill):
    name = "local_music"
    title = "点歌"

    def enabled(self, config):
        return bool((config.get("local_music") or {}).get("enabled"))

    def hotwords(self, config):
        extra = (config.get("local_music") or {}).get("hotwords") or []
        return HOTWORDS + ([extra] if isinstance(extra, str) else list(extra))

    def phrases(self, config):
        from core.gateway.skills.music.command import FIXED_REPLIES

        return FIXED_REPLIES

    def warm(self, conn):
        from core.gateway.skills.music.command import warm

        warm(conn)

    def on_listen(self, conn):
        from core.gateway.skills.music.command import duck

        duck(conn)

    async def handle(self, conn, text):
        from core.gateway.skills.music.command import handle_local_command

        return await handle_local_command(conn, text)
