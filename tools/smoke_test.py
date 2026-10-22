# -*- coding: utf-8 -*-
"""无微信环境下的回归测试：解析、折行、配置、卡片合并。

用法：
    python tools/smoke_test.py
不需要真实微信消息，也不会弹窗。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import config as cfgmod  # noqa: E402
from toast import Toast, ToastManager, wrap_text  # noqa: E402
from watcher import WeChatMessage, WeChatWatcher, parse_notification  # noqa: E402

FAILS: list[str] = []


def parse_wechat(texts, notif_id):
    """测试用：按微信通知解析（不带应用标识）。"""
    return parse_notification(texts, notif_id, "")


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}\n       期望: {want!r}\n       实际: {got!r}")
        FAILS.append(name)


def test_parse() -> None:
    print("[解析] 微信 Toast 文本 -> 消息对象")

    m = parse_wechat(["微信", "产品研发群", "张伟 : 这个版本的接口文档我下午更新一下"], 1)
    check("群消息拆分发送者", (m.source, m.sender, m.content),
          ("产品研发群", "张伟", "这个版本的接口文档我下午更新一下"))

    # 单聊正文里的中文冒号不该被当成分隔符（旧版的 bug）
    m = parse_wechat(["微信", "李静", "会议时间：明天下午三点，别忘了"], 2)
    check("单聊正文含中文冒号", (m.sender, m.content),
          ("", "会议时间：明天下午三点，别忘了"))

    m = parse_wechat(["微信", "李静", "好的，收到"], 3)
    check("单聊无冒号", (m.sender, m.content), ("", "好的，收到"))

    m = parse_wechat(["微信", "李静", "Bob: 我十分钟后到"], 4)
    check("正文里带英文冒号+空格", (m.sender, m.content), ("Bob", "我十分钟后到"))

    m = parse_wechat(["微信", "家里群", "妈：晚上回来吃饭吗，我做了汤"], 5)
    check("正文含句读标点不误判", m.sender, "")

    # 非微信通知现在走通用解析，由应用白名单决定要不要弹
    m = parse_wechat(["Python 3.13", "安装完成"], 6)
    check("非微信通知走通用解析", (m.source, m.content), ("Python 3.13", "安装完成"))
    check("文本行不足忽略", parse_wechat(["微信"], 7), None)
    check("图片消息正文为空", parse_wechat(["微信", "李静"], 8).content, "")


def test_wrap() -> None:
    print("[折行] 按像素宽度换行")
    fm = QFontMetrics(QFont("Microsoft YaHei UI"))
    body = QFont("Microsoft YaHei UI")
    body.setPixelSize(13)
    fm = QFontMetrics(body)

    lines = wrap_text("你好", fm, 200, max_lines=2)
    check("短文本一行", lines, ["你好"])

    lines = wrap_text("", fm, 200)
    check("空文本占位", lines, ["（新消息）"])

    long_cn = "这个版本的接口文档我下午更新一下，你们先按旧的对，我这边同步改一下联调脚本"
    lines = wrap_text(long_cn, fm, 200, max_lines=2)
    check("长中文折两行", len(lines), 2)
    check("长中文结尾省略号", lines[-1].endswith("…"), True)

    lines = wrap_text("Please check the configuration file carefully", fm, 160, max_lines=4)
    # 英文不能被拆成半个单词
    broken = [w for ln in lines for w in ln.replace("…", "").split()
              if w not in "Please check the configuration file carefully".split()]
    check("英文不拆词", broken, [])

    lines = wrap_text("第一行\n第二行\n第三行", fm, 400, max_lines=2)
    check("显式换行保留", lines, ["第一行", "第二行…"])

    lines = wrap_text("第一行\n第二行", fm, 400, max_lines=2)
    check("换行不超行数时不加省略号", lines, ["第一行", "第二行"])

    lines = wrap_text("a" * 300, fm, 100, max_lines=1)
    check("超长无空格串硬切", len(lines), 1)
    check("超长串加省略号", lines[0].endswith("…"), True)


def test_multi_app() -> None:
    print("[多应用] 通用解析与应用白名单")

    m = parse_notification(["任务已完成", "克隆并运行 wechat-notifier 项目"], 20, "WorkBuddy AI")
    check("通用应用取标题", m.source, "任务已完成")
    check("通用应用取正文", m.content, "克隆并运行 wechat-notifier 项目")
    check("通用应用标题带应用名", m.display_title, "WorkBuddy AI · 任务已完成")
    check("通用应用不算微信", m.is_wechat, False)

    m = parse_notification(["微信", "产品研发群", "张伟 : 在吗"], 21, "微信")
    check("微信仍走三段式", (m.source, m.sender, m.content),
          ("产品研发群", "张伟", "在吗"))

    # 关键：正文/标题里出现 wechat 不能把别的应用误判成微信
    w = WeChatWatcher(on_message=lambda x: None, enabled_apps=cfgmod.default_apps())
    check("标题含 wechat 的非微信应用被挡",
          w.app_enabled("WorkBuddy.WorkBuddyAI", "WorkBuddy AI",
                        ["克隆并运行 wechat-notifier 项目"]), False)
    check("微信 AUMID 命中", w.app_enabled("Tencent.WeChat", "微信", ["微信"]), True)
    check("Weixin 显示名命中", w.app_enabled("", "Weixin", ["微信"]), True)
    check("空名单什么都不弹",
          WeChatWatcher(on_message=lambda x: None, enabled_apps=[]).app_enabled("x", "微信", []),
          False)

    # 勾了其他应用就该放行
    w.set_enabled_apps([{"key": "wb", "name": "WorkBuddy AI",
                         "match": ["workbuddy ai", "workbuddyai.exe"]}])
    check("勾选后放行", w.app_enabled("WorkBuddy.WorkBuddyAI", "WorkBuddy AI", ["任务已完成"]), True)
    check("未勾选的应用仍被挡", w.app_enabled("Tencent.WeChat", "微信", ["微信"]), False)


def test_config() -> None:
    print("[配置] 规范化与兜底")
    c = cfgmod.normalize({
        "screen": "不存在的值",
        "ignore_sources": [" 某工作群 ", "", 123, "某工作群", "家庭群"],
        "card_width": 99999,
        "theme": "rainbow",
        "merge_same_source": 0,
    })
    check("非法屏幕回落", c["screen"], "cursor")
    check("免打扰清洗去重", c["ignore_sources"], ["某工作群", "家庭群"])
    check("宽度夹紧", c["card_width"], 560)
    check("主题回落", c["theme"], "dark")
    check("合并开关转布尔", c["merge_same_source"], False)
    check("新字段齐全", set(cfgmod.DEFAULT_CONFIG) <= set(c), True)

    # 应用名单：默认只有微信；脏数据要被清掉
    check("默认只监听微信", [a["name"] for a in cfgmod.default_apps()], ["微信"])
    check("默认名单落在配置里", [a["name"] for a in cfgmod.normalize({})["enabled_apps"]], ["微信"])

    c2 = cfgmod.normalize({"enabled_apps": [
        {"name": "微信", "match": ["微信", "微信", ""]},
        {"name": "", "match": ["x"]},
        "不是字典",
        {"name": "Chrome", "match": "chrome"},
    ]})
    check("应用名单清洗", [(a["name"], a["match"]) for a in c2["enabled_apps"]],
          [("微信", ["微信"]), ("Chrome", ["chrome"])])

    check("空名单保留为空", cfgmod.normalize({"enabled_apps": []})["enabled_apps"], [])


def test_toast(app: QApplication) -> None:
    print("[卡片] 渲染尺寸与同会话合并")
    cfg = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))

    m1 = WeChatMessage("产品研发群", "张伟", "第一条消息", time.time(), 1)
    t = Toast(m1, cfg)
    h1 = t.card_h
    check("卡片宽度", t.card_w, 340)
    check("单行正文高度", t.card_h, h1)

    m2 = WeChatMessage("产品研发群", "李静", "第二条消息，稍微长一点点", time.time(), 2)
    check("更新成功", t.update_message(m2), True)
    check("合并计数", t._count, 2)
    check("标题带条数", "（2）" in t.title_text, True)
    check("正文换成最新", t.msg.content, "第二条消息，稍微长一点点")
    t.close()
    t.deleteLater()

    manager = ToastManager(cfg, app)
    manager.push(WeChatMessage("家里群", "", "吃饭了", time.time(), 10))
    manager.push(WeChatMessage("家里群", "", "快点", time.time(), 11))
    check("同会话只留一张", len(manager.active), 1)
    check("条数累加", manager.active[0]._count, 2)

    manager.push(WeChatMessage("另一个群", "", "别的话题", time.time(), 12))
    check("不同会话新增一张", len(manager.active), 2)

    manager.cfg["merge_same_source"] = False
    manager.push(WeChatMessage("家里群", "", "第三条", time.time(), 13))
    check("关掉合并后新增", len(manager.active), 3)

    manager.close_all()

    # 简略模式：只显示「有一条新消息」
    cfg2 = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))
    cfg2["show_content"] = False
    t2 = Toast(WeChatMessage("产品研发群", "张伟", "这是不该被看到的内容", time.time(), 14), cfg2)
    check("简略模式正文", t2.body_lines, ["有一条新消息"])
    check("简略模式仍显示会话", t2.title_text, "产品研发群 · 张伟")
    t2.close()
    t2.deleteLater()


def test_migrate() -> None:
    """改名迁移：旧配置目录要能整目录搬过来。

    这里除了验行为，还顺便防一类隐蔽 bug：函数重名会静默覆盖前一个定义，
    单元测试不碰的话要等打出来的 exe 启动时才炸。
    """
    import shutil
    import tempfile

    print("[迁移] 改名前的配置目录搬迁")

    check("APP_NAME 是新名字", cfgmod.APP_NAME, "DesktopToast")
    check("旧名字有登记", bool(cfgmod.LEGACY_APP_NAME), True)

    root = tempfile.mkdtemp()
    try:
        legacy = os.path.join(root, cfgmod.LEGACY_APP_NAME)
        os.makedirs(legacy)
        with open(os.path.join(legacy, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"theme": "light"}')
        with open(os.path.join(legacy, "wechat-toast.log"), "w", encoding="utf-8") as f:
            f.write("old")

        target = os.path.join(root, cfgmod.APP_NAME)
        cfgmod._migrate_legacy_dir(root, target)

        check("新目录已生成", os.path.isdir(target), True)
        check("旧目录已消失", os.path.isdir(legacy), False)
        check(
            "配置跟过来了",
            os.path.exists(os.path.join(target, "config.json")),
            True,
        )
        check(
            "日志改成新名字",
            os.path.exists(os.path.join(target, "desktop-toast.log")),
            True,
        )
        check(
            "旧日志名不再存在",
            os.path.exists(os.path.join(target, "wechat-toast.log")),
            False,
        )

        # 新目录已存在时不能再搬，避免覆盖用户现在的配置
        cfgmod._migrate_legacy_dir(root, target)
        check("重复调用不出错", os.path.isdir(target), True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    app = QApplication(sys.argv)
    test_parse()
    test_wrap()
    test_multi_app()
    test_config()
    test_migrate()
    test_toast(app)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: {', '.join(FAILS)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
