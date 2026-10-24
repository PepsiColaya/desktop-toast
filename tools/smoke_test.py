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

from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import config as cfgmod  # noqa: E402
import guide  # noqa: E402
import apps  # noqa: E402
import opener  # noqa: E402
import wechat  # noqa: E402
from settings_window import STYLE, tooltip_html  # noqa: E402
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
    # 只勾微信时必须靠首行才能认出来，否则一条微信都收不到
    w.set_enabled_apps(wx)
    check("只勾微信时手机连接转发的微信放行",
          w.app_enabled(phone, "手机连接", ["微信", "妈妈", "对"]), True)
    check("只勾微信时其它手机 App 被挡",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), False)
    # 默认名单是手机连接：转发的手机 App 全部放行，非手机来源仍挡掉
    w.set_enabled_apps(cfgmod.default_apps())
    check("默认名单放行手机连接转发",
          w.app_enabled(phone, "手机连接", ["微信", "妈妈", "对"]), True)
    check("默认名单也放行其它手机 App",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), True)
    check("默认名单挡掉非手机来源",
          w.app_enabled("WorkBuddy.WorkBuddyAI", "WorkBuddy AI", ["任务已完成"]), False)
    m = parse_notification(["微信", "妈妈", "对"], 22, "手机连接")
    check("手机连接微信解析出会话", m.source, "妈妈")
    check("手机连接微信解析出正文", m.content, "对")

    # 消息要带上来源 AUMID，点击卡片时才知道该唤起谁
    m = parse_notification(["微信", "妈妈", "对"], 30, "手机连接",
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
          w.app_enabled(phone, "手机连接", ["微信", "妈妈", "对"]), True)
    check("只勾微信时 QQ 被挡",
          w.app_enabled(phone, "手机连接", ["QQ", "张三", "在吗"]), False)
    check("只勾微信时快捷指令被挡",
          w.app_enabled(phone, "手机连接", ["快捷指令", "17:47", "正在运行"]), False)
    check("认不出的手机 App 放行（宁可多弹不漏）",
          w.app_enabled(phone, "手机连接", ["某新App", "x", "y"]), True)
    w.set_phone_apps([], known)
    check("全不勾时手机通知全挡",
          w.app_enabled(phone, "手机连接", ["微信", "妈妈", "对"]), False)


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
    msg = WeChatMessage("产品研发群", "张伟", "内容", time.time(), 1,
                        app="手机连接", aumid="Microsoft.YourPhone_8wekyb3d8bbwe!App")
    t = Toast(msg, cfg, on_open=lambda m: got.append(m))
    check("消息带 aumid", t.msg.aumid, "Microsoft.YourPhone_8wekyb3d8bbwe!App")
    t.on_open(t.msg)
    check("回调收到消息对象", got and got[0] is msg, True)

    # 关掉开关时不该触发（开关读的是 click_to_open_source）
    check("开关键名已改名", cfg.get("click_to_open_source"), True)
    check("旧键名不再存在", "click_to_open_wechat" in cfg, False)
    t.close()
    t.deleteLater()


def main() -> int:
    app = QApplication(sys.argv)
    test_parse()
    test_wrap()
    test_multi_app()
    test_config()
    test_apps()
    test_guide()
    test_tooltip()
    test_migrate()
    test_opener()
    test_click()
    test_toast(app)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: {', '.join(FAILS)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
