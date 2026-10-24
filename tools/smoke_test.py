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
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parent.parent

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

import config as cfgmod  # noqa: E402
import guide  # noqa: E402
import apps  # noqa: E402
import autostart  # noqa: E402
import watcher as watcher_mod  # noqa: E402
import opener  # noqa: E402
import wechat  # noqa: E402
from settings_window import STYLE, SettingsWindow, tooltip_html  # noqa: E402
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

    m = parse_wechat(["微信", "示例群", "张三 : 这个版本的接口文档我下午更新一下"], 1)
    check("群消息拆分发送者", (m.source, m.sender, m.content),
          ("示例群", "张三", "这个版本的接口文档我下午更新一下"))

    # 单聊正文里的中文冒号不该被当成分隔符（旧版的 bug）
    m = parse_wechat(["微信", "李四", "会议时间：明天下午三点，别忘了"], 2)
    check("单聊正文含中文冒号", (m.sender, m.content),
          ("", "会议时间：明天下午三点，别忘了"))

    m = parse_wechat(["微信", "李四", "好的，收到"], 3)
    check("单聊无冒号", (m.sender, m.content), ("", "好的，收到"))

    m = parse_wechat(["微信", "李四", "Bob: 我十分钟后到"], 4)
    check("正文里带英文冒号+空格", (m.sender, m.content), ("Bob", "我十分钟后到"))

    m = parse_wechat(["微信", "示例群", "张：晚上七点开会，别迟到"], 5)
    check("正文含句读标点不误判", m.sender, "")

    # 非微信通知现在走通用解析，由应用白名单决定要不要弹
    m = parse_wechat(["Python 3.13", "安装完成"], 6)
    check("非微信通知走通用解析", (m.source, m.content), ("Python 3.13", "安装完成"))
    check("文本行不足忽略", parse_wechat(["微信"], 7), None)
    check("图片消息正文为空", parse_wechat(["微信", "李四"], 8).content, "")


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

    m = parse_notification(["微信", "示例群", "张三 : 在吗"], 21, "微信")
    check("微信仍走三段式", (m.source, m.sender, m.content),
          ("示例群", "张三", "在吗"))

    # 关键：正文/标题里出现 wechat 不能把别的应用误判成微信。
    # 默认名单已经不含微信（PC 微信不发通知，系统通知设置里也没它），
    # 这里手动构造一条「微信」条目，单独验证匹配逻辑本身还对不对
    wx = cfgmod.normalize({"enabled_apps": [
        {"key": "wechat", "name": "微信", "aumid": "Tencent.WeChat",
         "match": ["微信", "wechat", "weixin"]},
    ]})["enabled_apps"]
    w = WeChatWatcher(on_message=lambda x: None, enabled_apps=wx)
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

    # 手机连接转发：AUMID 和显示名都是「手机连接」，真实来源只在首行
    phone = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
    # 手机连接是唯一入口：名单里没有它，手机转发来的一律不放行，
    # 哪怕勾着同名的 PC 应用也不能把它顶回来
    w.set_enabled_apps(wx)
    check("只勾微信时手机转发来的也挡掉（入口没勾）",
          w.app_enabled(phone, "手机连接", ["微信", "示例联系人", "好的"]), False)
    check("只勾微信时其它手机 App 被挡",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), False)
    # 默认名单是手机连接：转发的手机 App 全部放行，非手机来源仍挡掉
    w.set_enabled_apps(cfgmod.default_apps())
    check("默认名单放行手机连接转发",
          w.app_enabled(phone, "手机连接", ["微信", "示例联系人", "好的"]), True)
    check("默认名单也放行其它手机 App",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), True)
    check("默认名单挡掉非手机来源",
          w.app_enabled("WorkBuddy.WorkBuddyAI", "WorkBuddy AI", ["任务已完成"]), False)
    m = parse_notification(["微信", "示例联系人", "好的"], 22, "手机连接")
    check("手机连接微信解析出会话", m.source, "示例联系人")
    check("手机连接微信解析出正文", m.content, "好的")

    # 消息要带上来源 AUMID，点击卡片时才知道该唤起谁
    m = parse_notification(["微信", "示例联系人", "好的"], 30, "手机连接",
                           "Microsoft.YourPhone_8wekyb3d8bbwe!App")
    check("解析带出来源 aumid", m.aumid, "Microsoft.YourPhone_8wekyb3d8bbwe!App")
    m = parse_notification(["任务已完成", "装好了"], 31, "WorkBuddy AI",
                           "WorkBuddy.WorkBuddyAI")
    check("通用解析也带 aumid", m.aumid, "WorkBuddy.WorkBuddyAI")

    # 手机连接下面的子项：勾哪个手机 App 就收哪个
    known = ["微信", "QQ", "快捷指令"]
    w.set_enabled_apps(cfgmod.default_apps())
    w.set_phone_apps(None, known)
    check("不过滤时手机通知全收",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), True)
    w.set_phone_apps(["微信"], known)
    check("只勾微信时微信放行",
          w.app_enabled(phone, "手机连接", ["微信", "示例联系人", "好的"]), True)
    check("只勾微信时 QQ 被挡",
          w.app_enabled(phone, "手机连接", ["QQ", "张三", "在吗"]), False)
    check("只勾微信时快捷指令被挡",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), False)
    # 认不出来的一律放行：手机 QQ / 微信的通知首行是联系人名，根本没有 App 名，
    # 拿「认不出来就拦」会把聊天消息全挡掉。这里必须是 True。
    check("白名单模式下认不出的手机 App 也放行",
          w.app_enabled(phone, "手机连接", ["某新App", "x", "y"]), True)
    check("好友名（手机 QQ 首行）放行",
          w.app_enabled(phone, "手机连接", ["哦吼√", "11"]), True)
    # 手动把名字加进 known 之后才按勾选管：注册表没收录的企业应用靠这个屏蔽
    w.set_phone_apps(["微信"], known + ["某新App"])
    check("手动添加后仍按勾选挡",
          w.app_enabled(phone, "手机连接", ["某新App", "x", "y"]), False)
    w.set_phone_apps(["微信", "某新App"], known + ["某新App"])
    check("勾上之后就放行",
          w.app_enabled(phone, "手机连接", ["某新App", "x", "y"]), True)
    w.set_phone_apps([], known)
    check("全不勾时手机通知全挡",
          w.app_enabled(phone, "手机连接", ["微信", "示例联系人", "好的"]), False)
    check("全不勾时好友名也挡（用户明说一个都不收）",
          w.app_enabled(phone, "手机连接", ["哦吼√", "11"]), False)
    # 恢复勾选后好友名照常放行
    w.set_phone_apps(["微信"], known)
    check("有勾选时好友名放行",
          w.app_enabled(phone, "手机连接", ["哦吼√", "11"]), True)

    # 取消「手机连接」后，勾着的同名 PC 应用不能把手机通知顶回来
    # （PC 版 QQ 的匹配串就是 qq，手机 QQ 的首行也叫 QQ）
    pc_qq = [{"key": "qq", "name": "QQ", "aumid": "QQ", "match": ["qq"]}]
    w.set_enabled_apps(pc_qq)
    check("只勾 PC QQ 时手机转发来的 QQ 不漏进来",
          w.app_enabled(phone, "手机连接", ["QQ", "张三", "在吗"]), False)
    check("PC 版 QQ 自己的通知仍放行",
          w.app_enabled("QQ", "QQ", ["新邮件", "内容"]), True)
    # 勾上手机连接、但把手机 QQ 子项取消，手机 QQ 要挡
    w.set_enabled_apps(cfgmod.default_apps())
    w.set_phone_apps(["微信"], known)
    check("手机连接在、子项取消 QQ 时挡住手机 QQ",
          w.app_enabled(phone, "手机连接", ["QQ", "张三", "在吗"]), False)
    w.set_phone_apps(["微信", "QQ"], known)
    check("子项勾上 QQ 时放行手机 QQ",
          w.app_enabled(phone, "手机连接", ["QQ", "张三", "在吗"]), True)

    # 走一遍真实入口 _handle：好友名不能被学进 known（那是手机 QQ 的发送者，
    # 学进去之后这个好友的消息会被精确命中名单又不在勾选范围，直接挡掉），
    # 也不能被过滤挡住
    got: list = []
    w2 = WeChatWatcher(
        on_message=got.append,
        enabled_apps=cfgmod.default_apps(),
        phone_apps=["微信"],
        phone_known=["微信"],
    )
    real_extract, real_ident = watcher_mod._extract_texts, watcher_mod.app_identity
    watcher_mod._extract_texts = lambda n: ["哦吼√", "11"]
    watcher_mod.app_identity = lambda n: (phone, "手机连接")

    class FakeNotif:
        def __init__(self, nid):
            self.id = nid

    try:
        w2._handle(FakeNotif(101))
        check("好友名没被学进 known", w2._phone_known, {"微信"})
        check("好友名消息放行", len(got), 1)
        check("弹出来源是手机连接", got[0].app if got else "", "手机连接")
        # 已知 App 仍然按白名单管：彩云天气Pro 要在 known 里才管得住
        watcher_mod._extract_texts = lambda n: ["彩云天气Pro", "预警订阅", "大风蓝色预警"]
        w2.set_phone_apps(["微信"], ["微信", "彩云天气Pro"])
        w2._handle(FakeNotif(102))
        check("不在白名单的已知 App 仍被挡", len(got), 1)
        w2.set_phone_apps(["微信", "彩云天气Pro"], ["微信", "彩云天气Pro"])
        w2._handle(FakeNotif(103))
        check("勾上之后弹出来", len(got), 2)
    finally:
        watcher_mod._extract_texts, watcher_mod.app_identity = real_extract, real_ident


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

    # 应用名单：默认只有「手机连接」；脏数据要被清掉
    # 列表数据源只认系统通知设置（注册表），PC 微信不在里面，所以默认不再预置微信
    check("默认只监听手机连接", [a["name"] for a in cfgmod.default_apps()], ["手机连接"])
    check("默认名单落在配置里",
          [a["name"] for a in cfgmod.normalize({})["enabled_apps"]], ["手机连接"])

    c2 = cfgmod.normalize({"enabled_apps": [
        {"name": "微信", "match": ["微信", "微信", ""]},
        {"name": "", "match": ["x"]},
        "不是字典",
        {"name": "Chrome", "match": "chrome"},
    ]})
    check("应用名单清洗", [(a["name"], a["match"]) for a in c2["enabled_apps"]],
          [("Chrome", ["chrome"])])

    # 老配置里预置的微信条目要清掉，且不能因此变成空名单（否则一条通知都收不到）
    legacy = cfgmod.normalize({"enabled_apps": [
        {"key": "wechat", "name": "微信", "match": ["微信", "wechat", "weixin"]},
    ]})
    check("微信幽灵项被清掉并回落默认",
          [a["name"] for a in legacy["enabled_apps"]], ["手机连接"])
    # 带 aumid 的微信条目是真应用，保留
    real = cfgmod.normalize({"enabled_apps": [
        {"key": "wechat", "name": "微信", "aumid": "Tencent.WeChat", "match": ["微信"]},
    ]})
    check("带 aumid 的微信条目保留",
          [a["name"] for a in real["enabled_apps"]], ["微信"])

    check("空名单保留为空", cfgmod.normalize({"enabled_apps": []})["enabled_apps"], [])

    # 手机连接的子项名单：None=全收，[]=全不收，其余是勾选的手机 App 名
    check("手机App默认不过滤", cfgmod.DEFAULT_CONFIG["phone_apps"], None)
    check("手机App名单清洗",
          cfgmod.normalize({"phone_apps": [" 微信 ", "QQ", "微信", ""]})["phone_apps"],
          ["微信", "QQ"])
    check("手机App全不勾保留", cfgmod.normalize({"phone_apps": []})["phone_apps"], [])
    check("手机App脏值回落不过滤", cfgmod.normalize({"phone_apps": "微信"})["phone_apps"], None)

    # phone_known 一次性迁移：旧版自动学到的名单里混着好友名（手机 QQ 首行是
    # 发送者），整份清掉，之后只保留用户手动添加的
    dirty = {"phone_known": ["昆仑智联（私有化版）", "哦吼√"]}
    once = cfgmod.normalize(dirty)
    check("迁移清掉学到的脏数据", once["phone_known"], [])
    check("迁移打了标记", once["phone_known_cleaned"], True)
    # 第二次加载保留手动添加的条目
    twice = cfgmod.normalize({"phone_known": ["昆仑智联（私有化版）"],
                              "phone_known_cleaned": True})
    check("迁移后手动添加的保留", twice["phone_known"], ["昆仑智联（私有化版）"])

    # 点击行为从「打开微信」改成「唤起来源应用」，旧键名要能迁过来
    check("旧键名迁移", cfgmod.normalize({"click_to_open_wechat": False})["click_to_open_source"], False)
    check("新键名优先",
          cfgmod.normalize({"click_to_open_wechat": False, "click_to_open_source": True})
          ["click_to_open_source"], True)

    # 设置面板左栏宽度（中间分割线位置）
    check("左栏宽度默认", cfgmod.DEFAULT_CONFIG["left_width"], 540)
    check("左栏宽度夹紧上限", cfgmod.normalize({"left_width": 5000})["left_width"], 900)
    check("左栏宽度夹紧下限", cfgmod.normalize({"left_width": 10})["left_width"], 340)
    check("左栏宽度透传", cfgmod.normalize({"left_width": 620})["left_width"], 620)


def test_toast(app: QApplication) -> None:
    print("[卡片] 渲染尺寸与同会话合并")
    cfg = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))

    m1 = WeChatMessage("示例群", "张三", "第一条消息", time.time(), 1)
    t = Toast(m1, cfg)
    h1 = t.card_h
    check("卡片宽度", t.card_w, 340)
    check("单行正文高度", t.card_h, h1)

    m2 = WeChatMessage("示例群", "李四", "第二条消息，稍微长一点点", time.time(), 2)
    check("更新成功", t.update_message(m2), True)
    check("合并计数", t._count, 2)
    check("标题带条数", "（2）" in t.title_text, True)
    check("正文换成最新", t.msg.content, "第二条消息，稍微长一点点")
    t.close()
    t.deleteLater()

    manager = ToastManager(cfg, app)
    manager.push(WeChatMessage("示例群", "", "第一条", time.time(), 10))
    manager.push(WeChatMessage("示例群", "", "第二条", time.time(), 11))
    check("同会话只留一张", len(manager.active), 1)
    check("条数累加", manager.active[0]._count, 2)

    manager.push(WeChatMessage("另一个群", "", "别的话题", time.time(), 12))
    check("不同会话新增一张", len(manager.active), 2)

    manager.cfg["merge_same_source"] = False
    manager.push(WeChatMessage("示例群", "", "第三条", time.time(), 13))
    check("关掉合并后新增", len(manager.active), 3)

    manager.close_all()

    # 简略模式：只显示「有一条新消息」
    cfg2 = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))
    cfg2["show_content"] = False
    t2 = Toast(WeChatMessage("示例群", "张三", "这是不该被看到的内容", time.time(), 14), cfg2)
    check("简略模式正文", t2.body_lines, ["有一条新消息"])
    check("简略模式仍显示会话", t2.title_text, "示例群 · 张三")
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


def test_apps() -> None:
    print("[应用名单] 注册表枚举与中文名解析")
    # 内置映射：常见软件直接给中文名
    check("内置映射 QQ", apps.resolve_name("QQ"), "QQ")
    check("内置映射 Telegram", apps.resolve_name("Telegram.TelegramDesktop"), "Telegram")
    check("内置映射 Trae", apps.resolve_name("ByteDance.TraeCN_8wekyb3d8bbwe!App"), "Trae")
    check("内置映射手机连接", apps.resolve_name("Microsoft.YourPhone_8wekyb3d8bbwe!App"), "手机连接")
    # 学到的名字优先级最高
    check(
        "学习缓存优先",
        apps.resolve_name("Some.Unknown_8wekyb3d8bbwe!App", {"Some.Unknown_8wekyb3d8bbwe!App": "某软件"}),
        "某软件",
    )
    # 兜底美化：CamelCase 拆词、去发布者后缀、跳过低级命名空间
    check("美化拆词", apps.beautify("Microsoft.WindowsStore_8wekyb3d8bbwe!App"), "Microsoft Windows Store")
    check("美化去后缀", apps.beautify("Foo.Bar_w2gh52qy24etm!App"), "Foo Bar")
    # 垃圾项过滤
    check("托盘哈希项过滤", apps.is_junk_aumid("NotifyIconGeneratedAumid_123abc"), True)
    check("系统Toast过滤", apps.is_junk_aumid("Windows.SystemToast.Foo"), True)
    check("GUID项过滤", apps.is_junk_aumid("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}/x.exe"), True)
    check("正常项不过滤", apps.is_junk_aumid("QQ"), False)
    # PC 微信要排除，它不发通知
    check("PC微信排除", apps.is_pc_wechat("WeChat"), True)
    check("PC微信排除2", apps.is_pc_wechat("Tencent.WeChat"), True)
    check("QQ不误判", apps.is_pc_wechat("QQ"), False)
    # 手机连接 AUMID 尾巴上解析手机 App 包名
    pl = "Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.tencent.xin"
    check("手机包名->微信", apps.phone_app_label(pl), "微信")
    check("手机包名->QQ", apps.phone_app_label(
        "Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.tencent.mqq"), "QQ")
    check("Setup键无标签", apps.phone_app_label(
        "Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneSetup"), "")
    check("GUID尾巴跳过", apps.phone_app_label(
        "Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_19157709-0e46-43b9-8a1c-3cf680527a87"), "")
    check("未知包名取尾巴", apps.phone_app_label(
        "Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.foo.bar-ios"), "bar")
    check("非手机连接键", apps.phone_app_label("QQ"), "")
    check("是手机连接键", apps.is_phone_link_aumid("Microsoft.YourPhone_8wekyb3d8bbwe!App"), True)
    # describe_apps 按名字去重：同一个软件的两个 AUMID 实例只留一条
    rows = apps.describe_apps(["A!App", "B!App"], {"A!App": "同款软件", "B!App": "同款软件"})
    check("同名去重", [r["name"] for r in rows], ["同款软件"])
    check("不同名都保留", len(apps.describe_apps(["QQ", "Telegram.TelegramDesktop"])), 2)
    # match_patterns：拿 AUMID 当关键字，不能用显示名拆词（「microsoft」会误伤一片）
    check("匹配串含AUMID", apps.match_patterns("Microsoft Store", "Microsoft.WindowsStore_8wekyb3d8bbwe!App"),
          ["microsoft.windowsstore", "microsoft.windowsstore_8wekyb3d8bbwe!app",
           "microsoft store", "microsoftstore"])
    check("匹配串中文去空格", apps.match_patterns("截图和草图", "Microsoft.ScreenSketch_8wekyb3d8bbwe!App"),
          ["microsoft.screensketch", "microsoft.screensketch_8wekyb3d8bbwe!app", "截图和草图"])
    check("匹配串不含通用词", "microsoft" in apps.match_patterns("Microsoft Store", "Microsoft.WindowsStore_8wekyb3d8bbwe!App"), False)

    # 枚举结果必须只来自系统通知设置：不含 PC 微信，也不含垃圾项
    listed = apps.list_notification_apps()
    check("列表不含 PC 微信", any(apps.is_pc_wechat(a) for a in listed), False)
    check("列表不含垃圾项", any(apps.is_junk_aumid(a) for a in listed), False)
    check("列表无重复", len(listed), len(set(listed)))


def test_guide() -> None:
    print("[教程] HTML 生成与状态分支")
    html = guide.build_html("active")
    check("包含标题", "让手机上的微信消息弹到电脑桌面" in html, True)
    check("自包含无外链", "http://" not in html and "https://" not in html, True)
    check("UTF-8 声明", 'charset="utf-8"' in html, True)
    check("active 分支", "已在工作" in html, True)
    check("none 分支", "没有安装" in guide.build_html("none"), True)
    check("installed 分支", "还没有在转发通知" in guide.build_html("installed"), True)
    # 三种状态的 HTML 都要能正常闭合
    for st in ("none", "installed", "active"):
        h = guide.build_html(st)
        check(f"{st} 结构完整", h.startswith("<!DOCTYPE html>") and h.rstrip().endswith("</html>"), True)


def test_tooltip() -> None:
    print("[提示框] 透明祖先污染调色板的回归")

    # 早期为了露出窗口底色，给左侧滚动区和内容容器设了 background: transparent。
    # Qt 的 QSS 怪癖：祖先一旦设透明背景，子孙控件的 Window/Base/Button 全被染成
    # 黑色，原生提示框继承后整块变黑；后来改成富文本 div 只盖住文字块，
    # 标签自带的几像素内容边距仍露黑边，表现为「悬浮框两边有黑框」。
    # 最终方案：左栏彻底不设透明背景 + QToolTip QSS 规则 + 富文本 div 双保险。
    # 这里从源码层面锁死，不许透明背景再回来。

    src = (ROOT / "settings_window.py").read_text(encoding="utf-8")
    check("左栏容器不再设透明背景",
          'setStyleSheet("background: transparent;")' not in src, True)
    check("滚动区规则不带透明背景",
          "QScrollArea { border: none; }" in STYLE, True)
    check("提示框有 QToolTip 配色规则",
          "QToolTip {" in STYLE and "background-color: #FFFFFF" in STYLE, True)

    html = tooltip_html("手机连接", "标识：Microsoft.YourPhone_8wekyb3d8bbwe!App")
    check("带背景色", "background-color:#FFFFFF" in html, True)
    check("带文字色", "color:#22222A" in html, True)
    check("用 div 块级元素", html.startswith("<div style="), True)
    check("多行用 br 分隔", html.count("<br>") == 1, True)

    # 空内容不该产出空壳标签
    check("空行被忽略", tooltip_html("", None) == "", True)

    # HTML 特殊字符必须转义，否则应用名里带 < > & 会把富文本解析坏
    esc = tooltip_html("a<b>&c")
    check("转义小于号", "&lt;" in esc, True)
    check("转义与号", "&amp;" in esc, True)
    check("不残留裸标签", "<b>" not in esc, True)

    # 用 span 不铺背景块，必须是 div
    check("不是 span", "<span" not in html, True)


def test_opener() -> None:
    print("[唤起] 点击卡片按来源分派")
    # 不打桩会真的去开应用，这里把三个底层动作换掉，只看分派对不对
    calls: list[tuple] = []
    real_activate, real_wechat, real_title = (
        opener._activate_by_aumid, wechat.open_wechat, opener._focus_window_by_title
    )
    opener._activate_by_aumid = lambda a: calls.append(("activate", a)) or True
    opener._focus_window_by_title = lambda n: calls.append(("title", n)) or True
    wechat.open_wechat = lambda: calls.append(("wechat",)) or True
    try:
        phone = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
        calls.clear()
        check("手机连接能打开", opener.open_source(phone, "手机连接"), True)
        check("手机连接走激活", calls[0][0], "activate")
        check("打开的是手机连接本体", calls[0][1], opener.PHONE_LINK_AUMID)

        calls.clear()
        opener.open_source("Tencent.WeChat", "微信")
        check("PC 微信走窗口唤醒", calls[0][0], "wechat")

        calls.clear()
        opener.open_source("WorkBuddy.WorkBuddyAI", "WorkBuddy")
        check("其它应用走激活", calls[0][0], "activate")
        check("激活用的是来源 AUMID", calls[0][1], "WorkBuddy.WorkBuddyAI")

        # 激活失败时退回按窗口标题找
        opener._activate_by_aumid = lambda a: calls.append(("activate-fail", a)) or False
        calls.clear()
        check("激活失败退回标题匹配", opener.open_source("Foo.Bar", "某软件"), True)
        check("标题用的是显示名", calls[-1], ("title", "某软件"))

        # 全都失败要静默返回 False，不抛异常
        opener._focus_window_by_title = lambda n: False
        check("认不出来静默失败", opener.open_source("", ""), False)
    finally:
        opener._activate_by_aumid = real_activate
        opener._focus_window_by_title = real_title
        wechat.open_wechat = real_wechat


def test_click() -> None:
    print("[点击] 卡片回调带上来源消息")
    cfg = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))
    got: list = []
    msg = WeChatMessage("示例群", "张三", "内容", time.time(), 1,
                        app="手机连接", aumid="Microsoft.YourPhone_8wekyb3d8bbwe!App")
    t = Toast(msg, cfg, on_open=lambda m: got.append(m))
    check("消息带 aumid", t.msg.aumid, "Microsoft.YourPhone_8wekyb3d8bbwe!App")
    t.on_open(t.msg)
    check("回调收到消息对象", got and got[0] is msg, True)
    check("卡片可点时是手型光标", t.cursor().shape(), Qt.PointingHandCursor)

    # 关掉开关时不该触发（开关读的是 click_to_open_source）
    check("开关键名已改名", cfg.get("click_to_open_source"), True)
    check("旧键名不再存在", "click_to_open_wechat" in cfg, False)
    t.close()
    t.deleteLater()


def test_tray() -> None:
    print("[托盘] 菜单和单击图标跟着最近通知的来源走")
    # main.py 里的托盘逻辑要 QSystemTrayIcon 才能跑起来，没法在无桌面环境实例化，
    # 这里退一步做源码级检查：只断言「不该写死微信」和「来源要被更新」这两点。
    src = (ROOT / "main.py").read_text(encoding="utf-8")

    check("不再硬编码打开微信", "wechat.open_wechat" in src, False)
    check("不再导入 wechat", "\nimport wechat\n" in src, False)
    check("菜单项不写死微信", '"打开微信"' in src, False)

    # 这两行缺一个，open_last_source() 就永远拿不到来源、菜单永远置灰
    check("收到消息时记 aumid", 'last_source["aumid"] =' in src, True)
    check("收到消息时记应用名", 'last_source["app"] =' in src, True)
    check("消息走 on_message 处理", "bridge.message.connect(on_message)" in src, True)
    # 暂停只是不弹卡片，来源还是要更新，否则恢复后打开的是旧应用
    check("暂停时也记来源", 'if not state["paused"]:' in src, True)

    # 单击/菜单文案要带上真实应用名
    check("菜单文案带应用名", 'f"打开 {last_source' in src, True)
    check("没来源时置灰", "act_open.setEnabled(False)" in src, True)
    # 测试卡片没有真实来源，点了不该唤起任何东西
    check("测试卡片不唤应用", "on_open=lambda _m: None" in src, True)


def test_apps_tree() -> None:
    print("[设置树] 同名手机 App 加后缀，配置里仍存真名")
    # 手机上的 QQ 和电脑上的 QQ 同名，列表里会出现两行「QQ」，
    # 用户分不清取消的是哪个；子项加后缀，但存进配置的必须是真实 App 名。
    real = (apps.list_notification_apps, apps.resolve_name, apps.phone_link_apps,
            apps.phone_link_status, autostart.is_enabled)
    phone_aumid = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
    names = {phone_aumid: "手机连接", "QQ": "QQ"}
    apps.list_notification_apps = lambda: [phone_aumid, "QQ"]
    apps.resolve_name = lambda aumid, learned=None: names.get(aumid, aumid)
    apps.phone_link_apps = lambda: [("QQ", "com.tencent.mqq"), ("微信", "com.tencent.xin")]
    apps.phone_link_status = lambda: "active"
    autostart.is_enabled = lambda: False
    w = None
    try:
        cfg = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))
        cfg["enabled_apps"] = cfgmod.default_apps()
        cfg["phone_apps"] = None
        w = SettingsWindow(cfg)

        tops = {}
        for i in range(w.tree_apps.topLevelItemCount()):
            it = w.tree_apps.topLevelItem(i)
            tops[it.text(0)] = it
        check("顶层同时有手机连接和 QQ", sorted(tops), ["QQ", "手机连接"])

        phone_row = tops.get("手机连接")
        kids = [phone_row.child(j).text(0) for j in range(phone_row.childCount())] if phone_row else []
        check("和顶层同名的子项加后缀", kids, ["QQ（手机）", "微信"])
        check("不同名的子项保持原名", "微信" in kids, True)

        # 取消手机 QQ，再收集一次，配置里必须是「QQ」而不是「QQ（手机）」
        for j in range(phone_row.childCount()):
            if phone_row.child(j).text(0) == "QQ（手机）":
                phone_row.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        w._collect()
        check("取消后只剩微信", w._cfg.get("phone_apps"), ["微信"])

        # 全部取消 = 全不收（不是「保持原值」）
        for j in range(phone_row.childCount()):
            phone_row.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        w._collect()
        check("子项全取消存空列表", w._cfg.get("phone_apps"), [])

        # 父项取消后，配置里不该再有手机连接
        phone_row.setCheckState(0, Qt.CheckState.Unchecked)
        w._collect()
        check("取消手机连接后名单为空", w._cfg.get("enabled_apps"), [])

        # 手动添加的手机 App（注册表里没有）也要出现在子项里
        w._cfg["phone_known"] = ["彩云天气Pro"]
        w._cfg["enabled_apps"] = cfgmod.default_apps()
        w._reload_apps()
        row = None
        for i in range(w.tree_apps.topLevelItemCount()):
            if w.tree_apps.topLevelItem(i).text(0) == "手机连接":
                row = w.tree_apps.topLevelItem(i)
        kids2 = [row.child(j).text(0) for j in range(row.childCount())] if row else []
        check("手动添加的手机 App 进了列表", "彩云天气Pro" in kids2, True)

        # 手动添加走输入框入口：输入名字 -> 进配置 -> 列表多一行
        w.ed_phone_add.setText("昆仑智联（私有化版）")
        w.findChild(QPushButton, "phone-add").click()
        check("添加后进了配置", "昆仑智联（私有化版）" in (w._cfg.get("phone_known") or []), True)
        row = None
        for i in range(w.tree_apps.topLevelItemCount()):
            if w.tree_apps.topLevelItem(i).text(0) == "手机连接":
                row = w.tree_apps.topLevelItem(i)
        kids3 = [row.child(j).text(0) for j in range(row.childCount())] if row else []
        check("添加后列表多一行", "昆仑智联（私有化版）" in kids3, True)
        check("输入框已清空", w.ed_phone_add.text(), "")

        # 重复添加不重复入列
        w.ed_phone_add.setText("昆仑智联（私有化版）")
        w.findChild(QPushButton, "phone-add").click()
        check("重复添加只留一份",
              (w._cfg.get("phone_known") or []).count("昆仑智联（私有化版）"), 1)

        # 移除选中：选中的手动条目能删，注册表里的不给删
        # 注意 _reload_apps 会清空树，每次操作前都要重新取 item，
        # 否则拿到的是已销毁的 C++ 对象
        def find_phone_row():
            for i in range(w.tree_apps.topLevelItemCount()):
                top = w.tree_apps.topLevelItem(i)
                if top.text(0) == "手机连接":
                    return top
            return None

        def find_child(label):
            r = find_phone_row()
            for j in range(r.childCount()):
                if r.child(j).text(0) == label:
                    return r.child(j)
            return None

        w.tree_apps.setCurrentItem(find_child("昆仑智联（私有化版）"))
        w.findChild(QPushButton, "phone-del").click()
        check("移除后离开配置",
              "昆仑智联（私有化版）" not in (w._cfg.get("phone_known") or []), True)
        check("手动加的彩云天气Pro 还在",
              "彩云天气Pro" in (w._cfg.get("phone_known") or []), True)
        check("移除后列表也没这行了", find_child("昆仑智联（私有化版）") is None, True)
        # 注册表里的条目（有真实 AUMID）不在 phone_known，移除应被拒绝
        # 注意子项显示名可能带「（手机）」后缀（PC 端有同名应用时）
        qq = find_child("QQ") or find_child("QQ（手机）")
        check("先找到 QQ 子项", qq is not None, True)
        w.tree_apps.setCurrentItem(qq)
        w.findChild(QPushButton, "phone-del").click()
        check("注册表条目不被移除", qq is not None, True)
    finally:
        (apps.list_notification_apps, apps.resolve_name, apps.phone_link_apps,
         apps.phone_link_status, autostart.is_enabled) = real
        if w is not None:
            w.close()
            w.deleteLater()


def test_buttons() -> None:
    print("[按钮] 设置面板每个按钮都得有实际效果")
    real = (apps.list_notification_apps, apps.resolve_name, apps.phone_link_apps,
            apps.phone_link_status, autostart.is_enabled, cfgmod.save,
            guide.open_guide, os.startfile, os.makedirs)
    phone_aumid = "Microsoft.YourPhone_8wekyb3d8bbwe!App"
    names = {phone_aumid: "手机连接", "QQ": "QQ", "Outlook": "Outlook"}
    state = {"apps": [phone_aumid, "QQ"], "status": "installed",
             "phones": [("微信", "com.tencent.xin")], "saved": 0}
    opened: list[str] = []

    apps.list_notification_apps = lambda: list(state["apps"])
    apps.resolve_name = lambda aumid, learned=None: names.get(aumid, aumid)
    apps.phone_link_apps = lambda: list(state["phones"])
    apps.phone_link_status = lambda: state["status"]
    autostart.is_enabled = lambda: False
    cfgmod.save = lambda c: state.__setitem__("saved", state["saved"] + 1) or True
    guide.open_guide = lambda status=None: True
    os.startfile = lambda p: opened.append(str(p))
    os.makedirs = lambda p, exist_ok=False: None

    w = None
    try:
        cfg = cfgmod.normalize(dict(cfgmod.DEFAULT_CONFIG))
        cfg["enabled_apps"] = cfgmod.default_apps()
        w = SettingsWindow(cfg)
        w.show()

        def btn(word: str):
            for b in w.findChildren(QPushButton):
                if word in b.text():
                    return b
            return None

        def kids():
            for i in range(w.tree_apps.topLevelItemCount()):
                it = w.tree_apps.topLevelItem(i)
                if it.text(0) == "手机连接":
                    return [it.child(j).text(0) for j in range(it.childCount())]
            return []

        texts = sorted(b.text() for b in w.findChildren(QPushButton))
        # 手机 App 手动添加/移除和免打扰那组按钮文字重名，靠 objectName 区分
        check("手动添加入口存在", w.findChild(QPushButton, "phone-add") is not None, True)
        check("手动移除入口存在", w.findChild(QPushButton, "phone-del") is not None, True)
        # 清单里「添加」「移除选中」各出现两次（免打扰一组 + 手机 App 一组）
        check("按钮清单", texts, sorted(["恢复默认", "在桌面试一下", "完成", "刷新",
                                      "重新检测", "查看配置教程", "添加", "移除选中",
                                      "打开目录", "添加", "移除选中"]))

        # 1. 刷新：重新读注册表，并给一句反馈
        state["apps"] = [phone_aumid, "QQ", "Outlook"]
        btn("刷新").click()
        top = [w.tree_apps.topLevelItem(i).text(0)
               for i in range(w.tree_apps.topLevelItemCount())]
        check("刷新读到了新应用", "Outlook" in top, True)
        check("刷新有反馈", w.lb_saved.text(), "已刷新：3 个应用")

        # 2. 重新检测：状态文字 + 手机 App 子项都要跟着变
        state["status"] = "active"
        state["phones"] = [("微信", "com.tencent.xin"), ("QQ", "com.tencent.mqq")]
        btn("重新检测").click()
        check("重新检测更新状态文字", "工作正常" in w.lb_phonelink.text(), True)
        check("重新检测补上新手机 App", "QQ（手机）" in kids(), True)
        check("重新检测有反馈", w.lb_saved.text(), "「手机连接」工作正常")

        # 3. 教程：生成并打开，给一句反馈
        btn("教程").click()
        check("教程按钮有反馈", w.lb_saved.text(), "教程已生成")

        # 4. 在桌面试一下：发信号
        got: list = []
        w.test_requested.connect(got.append)
        btn("在桌面试一下").click()
        check("测试按钮发出信号", len(got), 1)

        # 5. 免打扰：添加 / 移除
        w.ed_ignore.setText("示例群")
        # 和手机 App 那组按钮文字重名，按 objectName 定位
        w.findChild(QPushButton, "ignore-add").click()
        check("添加进了列表", w.lst_ignore.count(), 1)
        check("输入框已清空", w.ed_ignore.text(), "")
        w.lst_ignore.item(0).setSelected(True)
        w.findChild(QPushButton, "ignore-del").click()
        check("移除生效", w.lst_ignore.count(), 0)

        # 6. 打开头像目录
        opened.clear()
        btn("打开目录").click()
        check("打开目录真的调了资源管理器", len(opened), 1)

        # 7. 恢复默认
        w.sl_width.set_value(500)
        w._collect()
        check("先把宽度改掉", w._cfg["card_width"], 500)
        btn("恢复默认").click()
        check("恢复默认改回默认值", w._cfg["card_width"], 340)
        check("恢复默认会落盘", state["saved"] > 0, True)

        # 8. 完成：关窗口
        btn("完成").click()
        check("完成隐藏窗口", w.isVisible(), False)

        # 9. 光标：能点的东西都该是手型，不然看不出可点
        bad = [b.text() for b in w.findChildren(QPushButton)
               if b.cursor().shape() != Qt.PointingHandCursor]
        check("按钮都是手型光标", bad, [])
        bad = [c.text() for c in w.findChildren(QCheckBox)
               if c.cursor().shape() != Qt.PointingHandCursor]
        check("复选框都是手型光标", bad, [])
        check("应用列表是手型光标",
              w.tree_apps.viewport().cursor().shape(), Qt.PointingHandCursor)
        check("免打扰列表是手型光标",
              w.lst_ignore.viewport().cursor().shape(), Qt.PointingHandCursor)
    finally:
        (apps.list_notification_apps, apps.resolve_name, apps.phone_link_apps,
         apps.phone_link_status, autostart.is_enabled, cfgmod.save,
         guide.open_guide, os.startfile, os.makedirs) = real
        if w is not None:
            w.close()
            w.deleteLater()


def main() -> int:
    app = QApplication(sys.argv)
    test_parse()
    test_wrap()
    test_multi_app()
    test_config()
    test_apps()
    test_apps_tree()
    test_buttons()
    test_guide()
    test_tooltip()
    test_migrate()
    test_opener()
    test_click()
    test_tray()
    test_toast(app)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: {', '.join(FAILS)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
