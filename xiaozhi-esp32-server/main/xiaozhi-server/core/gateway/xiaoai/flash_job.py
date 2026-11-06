"""网关页面刷补丁固件的后台任务（G25 ③ 第 3 步）：代替 zongzhu-speaker/README.md 第 2–5 步。

页面上的操作（经 /gateway/api/control，要口令）：
- speaker_flash_start：{"version": 音箱现在的版本, "password": 要设的 root 密码, "confirm": true,
  "bootdelay": 可选 0–15, "slot": 可选 0 或 1，不填自动选}。先在电脑上做好镜像，再等音箱插电进刷机模式，接着备份、选边、写、核对、改启动参数
- 加 "dry_run": true 是"只读试一次"：不用填密码（做镜像用一次性的随机密码，做完就删），走到选边就停，
  一个字节都不写，只告诉页面会写哪一边。用来先确认这台电脑接得住音箱、选边对不对
- speaker_flash_cancel：做镜像和等插电的时候能停；开始写以后不能停（停在半路那一边就是坏的）
view() 放进 /gateway/api/status 的 "speaker_flash"。

选边：一边的 boot 和 system 都和官方包相同才算"官方的一边"。永远留一边官方的：
两边都是官方的写 0 号；只有一边是写另一边；两边都不是就停下不写（多半是版本填错了，或者音箱已经不是原样）。
页面上也能自己选写 0 号还是 1 号，但另一边必须是官方的，不然写了就没有退路，照样不写。
任何一步失败就停，不改启动参数，音箱照旧从原来那一边启动。只读备份留在 data/xiaoai-flash/backup-*；
做好的镜像（里面有密码串）刷完或失败都删掉。
"""
import asyncio
import hashlib
import secrets
import shutil
import time
from pathlib import Path

from config.logger import setup_logging
from core.gateway.control import ControlError
from core.gateway.xiaoai import flash, image

TAG = __name__
logger = setup_logging()

ACTIONS = {"speaker_flash_start", "speaker_flash_cancel"}
STEPS = ("检查电脑上的工具", "查官方包", "下载官方包", "做补丁镜像", "等音箱进刷机模式", "只读备份", "选边",
         "写内核", "写系统", "改启动参数")
WAIT_SECONDS = 240
BACKUP = ("boot0", "boot1", "system0", "system1", "bootloader", "tpl")

# state: idle / running / done / error / cancelled；steps: [{"name", "state": running/done/error, "detail"}]
job = {"state": "idle", "steps": [], "error": "", "result": None, "writing": False, "dry_run": False, "started": 0}
DRY_RUN_STEPS = STEPS[:STEPS.index("选边") + 1]
_task = None


def view() -> dict:
    return {"check": flash.check(), "tested": list(image.TESTED), "steps": list(STEPS), "dry_run_steps": list(DRY_RUN_STEPS),
            "job": dict(job, steps=[dict(s) for s in job["steps"]])}


def _step(name, detail=""):
    if job["steps"] and job["steps"][-1]["state"] == "running":
        job["steps"][-1]["state"] = "done"
    job["steps"].append({"name": name, "state": "running", "detail": detail})
    return job["steps"][-1]


def _detail(text):
    job["steps"][-1]["detail"] = text


def _same_start(path, reference) -> bool:
    """分区读出来的前面一段和 reference 文件逐字节相同（分区比文件大，后面是 0xff 或别的）"""
    size = Path(reference).stat().st_size
    with open(path, "rb") as a, open(reference, "rb") as b:
        while size:
            n = min(size, 1 << 20)
            if a.read(n) != b.read(n):
                return False
            size -= n
    return True


def choose_slot(backup: Path, extracted: Path, wanted=None):
    """返回 (要写的那一边 0/1, 说明)；不能写返回 (None, 原因)。wanted：页面上选的那一边，不选就自动"""
    official = [_same_start(backup / f"boot{s}.img", extracted / "boot.img.encrypt")
                and _same_start(backup / f"system{s}.img", extracted / "root.squashfs") for s in (0, 1)]
    if wanted is not None:
        other = 1 - wanted
        if not official[other]:
            return None, (f"你选了写 {wanted} 号，但 {other} 号不是官方系统，写了就没有退路，没有写"
                          + (f"；按备份比对，应该写 {other} 号" if official[wanted] else ""))
        return wanted, f"按你选的写 {wanted} 号，{other} 号是官方系统，留着当退路"
    if all(official):
        return 0, "两边都是官方系统，写 0 号，1 号留着当退路"
    if official[1]:
        return 0, "1 号是官方系统，留着当退路，写 0 号"
    if official[0]:
        return 1, "0 号是官方系统，留着当退路，写 1 号"
    return None, "两边都和官方包对不上，没有写：确认填的版本就是音箱现在的版本（米家 App 里看），音箱没被改过"


async def _write(tool, partition, source, folder):
    """写进去、读回来核对，最多 2 次"""
    for attempt in (1, 2):
        _detail(f"第 {attempt} 次写入")
        await tool.partition(partition, source)
        _detail(f"第 {attempt} 次读回核对")
        readback = await tool.mread(partition, folder / f"{partition}.readback")
        same = await asyncio.to_thread(_same_start, readback, source)
        readback.unlink(missing_ok=True)
        if same:
            _detail(f"写入并读回核对一致（第 {attempt} 次）")
            return
    raise flash.FlashError(f"{partition} 写了两次，读回来都和镜像不一致；启动参数没改，音箱照旧从原来那一边启动")


async def _run(version, password, bootdelay, dry_run=False, wanted=None):
    built = None
    log_lines = []
    try:
        _step(STEPS[0])
        checked = await asyncio.to_thread(flash.check)
        if not checked["ok"]:
            raise flash.FlashError("；".join(checked["missing"]))
        tool = flash.Update(await flash.ensure_update(), log=log_lines.append)

        _step(STEPS[1])
        info = await image.query(version)
        _detail(f"{info['version']}，{info['size'] // 1_000_000} MB")

        _step(STEPS[2])
        firmware = await asyncio.to_thread(
            image.download, info, lambda done, total: _detail(f"{done * 100 // max(total, 1)}%"))
        _detail("已下好，MD5 核对一致")

        _step(STEPS[3])
        built = await image.build(firmware, password, _detail)
        password = None
        _detail(f"做好了，{built['size']} 字节，核对通过")

        _step(STEPS[4], f"拔掉音箱电源再插上（{WAIT_SECONDS // 60} 分钟内）")
        await flash.wait_device(WAIT_SECONDS)
        version_id = await tool.identify()
        _detail(f"接住了（刷机程序 {version_id}）")

        job["writing"] = True  # 从这里起不能停：备份虽然只读，但音箱已经停在刷机模式，后面要一口气做完
        folder = _new_folder(image.work_dir() / time.strftime("backup-%Y%m%d-%H%M%S"))
        _step(STEPS[5], str(folder))
        sums = []
        for i, name in enumerate(BACKUP, 1):
            _detail(f"读 {name}（{i}/{len(BACKUP)}）")
            path = await tool.mread(name, folder / f"{name}.img")
            sums.append(f"{await asyncio.to_thread(_md5, path)}  {path.name}")
        (folder / "md5.txt").write_text("\n".join(sums) + "\n")
        _detail(f"6 个分区都读出来了：{folder}")

        _step(STEPS[6])
        slot, why = await asyncio.to_thread(choose_slot, folder, built["dir"] / "extracted", wanted)
        if slot is None:
            raise flash.FlashError(why)
        _detail(why)
        if dry_run:
            job["steps"][-1]["state"] = "done"
            job.update(state="done", result={"dry_run": True, "slot": slot, "kept": 1 - slot, "version": info["version"],
                                             "backup": str(folder), "tested": info["version"] in image.TESTED})
            logger.bind(tag=TAG).info(f"网关页面只读试刷音箱：{info['version']} 会写 {slot} 号，备份 {folder}")
            return

        _step(STEPS[7], f"boot{slot}")
        await _write(tool, f"boot{slot}", built["kernel"], built["dir"])
        _step(STEPS[8], f"system{slot}")
        await _write(tool, f"system{slot}", built["rootfs"], built["dir"])

        _step(STEPS[9])
        if bootdelay is not None:
            await tool.bulkcmd(f"setenv bootdelay {bootdelay}")
        await tool.bulkcmd(f"setenv boot_part boot{slot}")
        await tool.bulkcmd("saveenv")
        _detail(f"从 boot{slot} 启动")
        job["steps"][-1]["state"] = "done"
        job.update(state="done", result={"slot": slot, "kept": 1 - slot, "version": info["version"],
                                         "backup": str(folder), "tested": info["version"] in image.TESTED})
        logger.bind(tag=TAG).info(f"网关页面给音箱刷好了补丁固件：{info['version']} 写在 {slot} 号，备份 {folder}")
    except asyncio.CancelledError:
        _fail("停下了，什么都没写", "cancelled")
        raise
    except (flash.FlashError, image.ImageError) as e:
        _fail(str(e))
    except Exception as e:
        _fail(f"出错了：{type(e).__name__} {e}"[:300])
    finally:
        if built:
            shutil.rmtree(built["dir"], ignore_errors=True)  # 里面有密码串
        if log_lines and job["state"] != "done":
            logger.bind(tag=TAG).warning("刷机工具最后的输出：" + log_lines[-1][-500:])
        job["writing"] = False


def _fail(message, state="error"):
    if job["steps"] and job["steps"][-1]["state"] == "running":
        job["steps"][-1]["state"] = "error"
    job.update(state=state, error=message)
    if state == "error":
        logger.bind(tag=TAG).warning(f"网关页面刷音箱没成：{message}")


def _new_folder(path: Path) -> Path:
    """建一个新的空目录（700）；同一秒里已经有了就加 -2、-3"""
    for n in range(1, 100):
        folder = path if n == 1 else path.with_name(f"{path.name}-{n}")
        try:
            folder.mkdir(mode=0o700)
            return folder
        except FileExistsError:
            continue
    raise flash.FlashError(f"建不了备份目录：{path}")


def _md5(path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def act(config, action, value) -> dict:
    global _task
    value = value if isinstance(value, dict) else {}
    if action == "speaker_flash_cancel":
        if job["state"] != "running":
            return {"message": "没有在刷。"}
        if job["writing"]:
            raise ControlError("已经在读写音箱了，不能停；等它做完")
        _task.cancel()
        return {"message": "停下了。"}
    if job["state"] == "running":
        raise ControlError("正在刷，等这次做完")
    dry_run = value.get("dry_run") is True
    if dry_run:
        value = dict(value, password=secrets.token_urlsafe(16), confirm=True, bootdelay=None)  # slot 照样用  # 镜像只用来比对，做完就删
    if value.get("confirm") is not True:
        raise ControlError("要先确认知道刷机的风险")
    try:
        version = image.check_version(value.get("version"))
        password = image.check_password(value.get("password"))
    except image.ImageError as e:
        raise ControlError(str(e)) from None
    bootdelay = value.get("bootdelay")
    if bootdelay is not None and not (isinstance(bootdelay, int) and 0 <= bootdelay <= 15):
        raise ControlError("bootdelay 要是 0–15 的整数")
    wanted = value.get("slot")
    if wanted is not None and wanted not in (0, 1) or isinstance(wanted, bool):
        raise ControlError("写哪一边只能选 0 号或 1 号，不选就自动")
    job.update(state="running", steps=[], error="", result=None, writing=False, dry_run=dry_run, started=time.time())
    _task = asyncio.create_task(_run(version, password, bootdelay, dry_run, wanted))
    if dry_run:
        return {"message": f"开始只读试一次（{version}，不写音箱）；做好镜像后会提示你拔电再插。"}
    return {"message": f"开始准备 {version} 的补丁固件；做好镜像后会提示你拔电再插。"}
