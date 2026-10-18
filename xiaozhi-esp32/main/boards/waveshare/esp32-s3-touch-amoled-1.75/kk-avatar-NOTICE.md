# KK avatar adaptation

Eye proportions and expression concepts in `kk_avatar.h` are adapted from
[Trentct/m5stack-stopwatch-avatar](https://github.com/Trentct/m5stack-stopwatch-avatar),
commit `204963257cb4dc2f3d7501eff900897bac55ef82`, under AGPL-3.0-or-later.
The license is retained in `kk-avatar-LICENSE`.

`avatar_round_display.h` adapts the XiaoZhi/Waveshare round-screen layout and
implements this visual style with LVGL objects. The source M5Unified renderer,
hardware drivers and 60 fps timing are not transplanted.

Since 2.5.2.5, `avatar_round_display.h` also handles touch gestures and
`qmi8658_motion.h` drives tilt gaze and shake-to-dizzy for the board's QMI8658.
They are written for this board (CST9217 touch via LVGL, QMI8658 registers);
gesture and shake thresholds follow the upstream firmware's values.
The adapted avatar files are provided under AGPL-3.0-or-later; original XiaoZhi
code retains its existing notices. Keep these notices and corresponding source
with releases containing the adaptation.

This version keeps the voice assistant status, waiting time and subtitles.
Speaking uses a gentle eye pulse; it is not audio-amplitude lip synchronization.
The update timer targets about 30 fps; no measured frame-rate claim is made.
