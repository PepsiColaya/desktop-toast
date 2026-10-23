# -*- coding: utf-8 -*-
"""生成本地 HTML 版《手机连接配置教程》，点按钮直接用浏览器打开。

做成单个自包含 HTML：不依赖网络、不依赖本地图片，复制到别的电脑也能看。
样式沿用程序的品牌靛蓝 #4C5BD4，和设置面板视觉一致。
"""
from __future__ import annotations

import os

import config as cfgmod

GUIDE_NAME = "手机连接配置教程.html"

BRAND = "#4C5BD4"

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    margin: 0; padding: 0;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    background: #F4F5FA; color: #22222A; line-height: 1.75;
    -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 780px; margin: 0 auto; padding: 40px 24px 64px; }
.hero {
    background: linear-gradient(135deg, #4C5BD4 0%, #6B7BF0 100%);
    border-radius: 18px; padding: 30px 32px; color: #FFFFFF;
    box-shadow: 0 12px 32px rgba(76, 91, 212, .22);
}
.hero h1 { margin: 0 0 8px; font-size: 25px; letter-spacing: .5px; }
.hero p { margin: 0; opacity: .92; font-size: 14px; }
.card {
    background: #FFFFFF; border: 1px solid #E6E7F0; border-radius: 14px;
    padding: 22px 26px; margin-top: 18px;
    box-shadow: 0 2px 10px rgba(34, 34, 42, .04);
}
h2 {
    font-size: 17px; margin: 0 0 4px; color: #22222A;
    display: flex; align-items: center; gap: 10px;
}
h2 .num {
    flex: 0 0 auto; width: 26px; height: 26px; border-radius: 8px;
    background: #EEF0FD; color: #4C5BD4; font-size: 13px; font-weight: 700;
    display: inline-flex; align-items: center; justify-content: center;
}
.sub { color: #8A8A96; font-size: 13px; margin: 0 0 14px 36px; }
ol, ul { margin: 0 0 0 36px; padding-left: 20px; }
li { margin: 7px 0; font-size: 14px; }
li > ul, li > ol { margin-top: 4px; }
b, strong { color: #4C5BD4; font-weight: 600; }
code {
    background: #F1F2F8; border: 1px solid #E4E5EF; border-radius: 5px;
    padding: 1px 6px; font-size: 12.5px; color: #3A3A46;
    font-family: Consolas, "Courier New", monospace;
}
.tip {
    background: #FFF8EC; border: 1px solid #F5E2BE; border-left: 4px solid #F2994A;
    border-radius: 9px; padding: 12px 16px; margin: 14px 0 0 36px; font-size: 13px;
}
.tip b { color: #C97A12; }
.ok {
    background: #EEFBF3; border: 1px solid #C6EBd6; border-left: 4px solid #07C160;
    border-radius: 9px; padding: 12px 16px; margin: 14px 0 0 36px; font-size: 13px;
}
.ok b { color: #059048; }
table { width: calc(100% - 36px); margin: 12px 0 0 36px; border-collapse: collapse; font-size: 13.5px; }
th, td { border: 1px solid #E6E7F0; padding: 9px 12px; text-align: left; vertical-align: top; }
th { background: #F7F8FC; color: #4A4A56; font-weight: 600; white-space: nowrap; }
td:first-child { color: #4C5BD4; font-weight: 600; white-space: nowrap; }
.foot { text-align: center; color: #A0A0AC; font-size: 12px; margin-top: 26px; }
.kbd {
    display: inline-block; background: #FFFFFF; border: 1px solid #D8D9E4;
    border-bottom-width: 2px; border-radius: 5px; padding: 0 6px;
    font-size: 12px; color: #3A3A46; font-family: Consolas, monospace;
}
a { color: #4C5BD4; }
.steps { counter-reset: s; list-style: none; padding-left: 0; margin-left: 36px; }
.steps > li { position: relative; padding-left: 34px; margin: 12px 0; }
.steps > li::before {
    counter-increment: s; content: counter(s);
    position: absolute; left: 0; top: 2px;
    width: 22px; height: 22px; border-radius: 50%;
    background: #4C5BD4; color: #fff; font-size: 12px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
}
"""


def _status_block(status: str) -> str:
    """按检测结果显示一段说明。"""
    if status == "none":
        return (
            '<div class="tip"><b>检测结果：本机没有安装「手机连接」。</b><br>'
            "下面的第 1 步会告诉你从哪里装。装好、配对完再回来勾选监听。</div>"
        )
    if status == "installed":
        return (
            '<div class="tip"><b>检测结果：本机已安装「手机连接」，但还没有在转发通知。</b><br>'
            "大概率是没配对成功，或者没打开通知转发。请重点看第 3、4 步。</div>"
        )
    return (
        '<div class="ok"><b>检测结果：「手机连接」已在工作。</b><br>'
        "监听应用里勾选「手机连接」，微信等手机 App 的消息就会弹到桌面上了。"
        "如果收不到，重点看第 5 步和第 6 步。</div>"
    )


def build_html(status: str = "installed") -> str:
    """生成完整 HTML。status 取 apps.phone_link_status() 的返回值。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>手机连接配置教程 · DesktopToast</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">

<div class="hero">
    <h1>让手机上的微信消息弹到电脑桌面</h1>
    <p>PC 版微信自己不往 Windows 消息中心发通知，但手机上的微信会。
    借「手机连接」把手机通知转发到电脑，本程序就能读到并弹卡片。</p>
</div>

{_status_block(status)}

<div class="card">
    <h2><span class="num">1</span>安装「手机连接」</h2>
    <p class="sub">Windows 10 / 11 自带，但可能被卸载或禁用</p>
    <ol class="steps">
        <li>按 <span class="kbd">Win</span> + <span class="kbd">S</span> 搜索
            <code>手机连接</code> 或 <code>Phone Link</code>，搜得到就直接打开。</li>
        <li>搜不到就打开 Microsoft Store，搜索 <b>手机连接</b>（发布者是 Microsoft Corporation），点安装。</li>
        <li>安装完在开始菜单里找到它并打开。</li>
    </ol>
    <div class="tip"><b>注意：</b>手机要装对应的 App ——
    Android 用「链接到 Windows」，iPhone 才用这里说的「手机连接」（Phone Link）。
    两个名字指的是同一套东西。</div>
</div>

<div class="card">
    <h2><span class="num">2</span>配对手机</h2>
    <p class="sub">电脑和手机都要联网，建议连同一个 Wi-Fi</p>
    <ol class="steps">
        <li>在电脑的「手机连接」里勾选 <b>我有相应的手机</b>，用摄像头扫屏幕上的二维码。</li>
        <li>也可以点 <b>手动配对</b>，按提示在手机上输入几位数字。</li>
        <li>iPhone 用户：手机上会弹「蓝牙配对请求」，点 <b>配对</b>；
            再在设置里允许访问通讯录、通知。</li>
        <li>Android 用户：在手机上打开「链接到 Windows」，用相机扫电脑二维码，
            按提示授予权限。</li>
    </ol>
    <div class="tip"><b>配对失败的常见原因：</b>蓝牙没开、手机和电脑隔得太远、
    手机上没登录微软账号、公司网络隔离了设备发现。换到同一 Wi-Fi 下再试。</div>
</div>

<div class="card">
    <h2><span class="num">3</span>打开「手机通知」转发</h2>
    <p class="sub">这一步才是把手机消息送到电脑的关键开关</p>
    <ol class="steps">
        <li>在「手机连接」窗口左侧点 <b>通知</b>。</li>
        <li>把顶部的开关拨到 <b>开</b>。</li>
        <li>下方会出现手机 App 列表，确认 <b>微信</b> 是打开的。</li>
    </ol>
    <div class="ok"><b>自检：</b>开关打开后，让手机收到一条微信，
    电脑右下角应该立刻弹出一条「手机连接 · 微信」的通知。弹出来了就说明这一步成功了。</div>
</div>

<div class="card">
    <h2><span class="num">4</span>确认 Windows 允许「手机连接」发通知</h2>
    <p class="sub">转发开关开了，但系统把通知拦了，一样看不到</p>
    <ol class="steps">
        <li>按 <span class="kbd">Win</span> + <span class="kbd">I</span> 打开设置。</li>
        <li>进 <b>系统 → 通知</b>，确认「通知」总开关是开的。</li>
        <li>在应用列表里找到 <b>手机连接</b>，把它的开关也打开。</li>
        <li>顺手把「通知中心显示通知」「播放通知声音」按需要勾上。</li>
    </ol>
</div>

<div class="card">
    <h2><span class="num">5</span>在本程序里勾选「手机连接」</h2>
    <p class="sub">只勾了微信是不够的，因为微信的通知是借手机连接的口进来的</p>
    <ol class="steps">
        <li>右键托盘图标 → <b>设置</b>，打开「监听应用」一栏。</li>
        <li>在列表里勾选 <b>手机连接</b>。</li>
        <li>如果列表里没有它，点一下 <b>刷新</b>；还是没有就回到第 3、4 步检查。</li>
        <li>「免打扰」里可以填手机上的群名或备注名，和微信里显示的一致。</li>
    </ol>
    <div class="tip"><b>为什么监听应用里看不到 PC 微信？</b><br>
    PC 微信根本不往 Windows 消息中心发通知，列出来也只是个点不动的选项，
    所以程序只列「设置 → 系统 → 通知」里真正出现过通知的应用。</div>
</div>

<div class="card">
    <h2><span class="num">6</span>常见问题</h2>
    <table>
        <tr><th>现象</th><th>原因与处理</th></tr>
        <tr><td>勾了手机连接还是不弹</td>
            <td>通知被「免打扰」挡了；或手机的微信没在手机连接的通知白名单里</td></tr>
        <tr><td>卡片上显示的是英文进程名</td>
            <td>等该应用真的发过一条通知，程序就会自动学到中文名并记住</td></tr>
        <tr><td>群消息里看不到发送者</td>
            <td>手机连接转发的通知有时不带发送者，这是系统限制</td></tr>
        <tr><td>iPhone 收不到</td>
            <td>iOS 对通知转发限制更严，部分 App 不支持；微信一般可以</td></tr>
        <tr><td>重启电脑后失效</td>
            <td>勾选设置里的「开机自动启动」，并保持手机连接在后台</td></tr>
    </table>
</div>

<div class="foot">本文档由 DesktopToast 自动生成，可离线查看 · 按 F5 刷新本页不会丢内容</div>

</div>
</body>
</html>
"""


def guide_path() -> str:
    return os.path.join(cfgmod.config_dir(), GUIDE_NAME)


def write_guide(status: str = "installed") -> str:
    """把教程写进配置目录，返回文件路径。"""
    path = guide_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_html(status))
    except Exception:
        return ""
    return path


def open_guide(status: str = "installed") -> bool:
    """生成并直接用默认浏览器打开。"""
    path = write_guide(status)
    if not path:
        return False
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False
