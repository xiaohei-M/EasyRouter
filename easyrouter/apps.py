# -*- coding: utf-8 -*-
"""应用识别：根据 DNS 域名特征归类常见应用。"""
import re

# (关键字列表, 应用名, 分类, 图标)
RULES = [
    (("weixin.qq.com", "wx.qq.com", "wechat.com", "weixinbridge"), "微信", "即时通讯", "💬"),
    (("qq.com", "qzone", "qpic.cn"), "QQ", "即时通讯", "🐧"),
    (("dingtalk", "dingtalkapps"), "钉钉", "办公", "📌"),
    (("feishu", "larksuite", "bytedance.net"), "飞书", "办公", "📌"),
    (("telegram", "t.me"), "Telegram", "即时通讯", "✈️"),
    (("whatsapp",), "WhatsApp", "即时通讯", "💬"),
    (("douyin", "amemv", "douyinvod", "snssdk", "byteimg", "iesdouyin"), "抖音", "短视频", "🎵"),
    (("tiktok", "tiktokcdn"), "TikTok", "短视频", "🎵"),
    (("kuaishou", "gifshow", "kwaicdn", "kuaishouzt"), "快手", "短视频", "⚡"),
    (("xiaohongshu", "xhscdn"), "小红书", "社交", "📕"),
    (("weibo", "sinaimg", "wbcdn"), "微博", "社交", "🌐"),
    (("bilibili", "bilivideo", "hdslb", "biliapi"), "哔哩哔哩", "视频", "📺"),
    (("iqiyi", "qiyi", "71.am"), "爱奇艺", "视频", "🎬"),
    (("v.qq.com", "qqvideo", "gtimg"), "腾讯视频", "视频", "🎬"),
    (("youku", "tudou"), "优酷", "视频", "🎬"),
    (("mgtv", "hunantv"), "芒果TV", "视频", "🥭"),
    (("y.qq.com", "qqmusic", "music.163", "126.net"), "音乐", "音乐", "🎧"),
    (("taobao", "tmall", "alicdn", "alipay", "alipayobjects"), "淘宝/支付宝", "购物支付", "🛒"),
    (("jd.com", "360buyimg", "jdcdn"), "京东", "购物", "🛍️"),
    (("pinduoduo", "yangkeduo"), "拼多多", "购物", "🛍️"),
    (("meituan", "dianping", "sankuai"), "美团", "生活", "🍜"),
    (("ele.me", "eleme"), "饿了么", "生活", "🍱"),
    (("baidu", "bdstatic", "bdimg"), "百度", "搜索", "🔍"),
    (("zhihu", "zhimg"), "知乎", "内容", "📚"),
    (("toutiao", "pstatp", "bytedance"), "今日头条", "内容", "📰"),
    (("netease", "163.com"), "网易", "内容", "📰"),
    (("mihoyo", "hoyoverse", "yuanshen"), "米哈游", "游戏", "🎮"),
    (("steampowered", "steamcontent", "steamstatic"), "Steam", "游戏", "🎮"),
    (("epicgames", "unrealengine"), "Epic", "游戏", "🎮"),
    (("pvp.qq.com", "tencentgame", "gcloud.qq.com"), "腾讯游戏", "游戏", "🎮"),
    (("blizzard", "battle.net"), "暴雪战网", "游戏", "🎮"),
    (("xboxlive", "playstation", "nintendo"), "主机游戏", "游戏", "🎮"),
    (("apple.com", "icloud", "mzstatic", "aaplimg"), "Apple 服务", "系统", "🍎"),
    (("microsoft", "windowsupdate", "live.com", "msftconnecttest"), "Windows 更新", "系统", "🪟"),
    (("google", "gstatic", "googleapis"), "Google", "系统", "🔎"),
    (("github", "githubusercontent"), "GitHub", "开发", "🐙"),
    (("openai", "chatgpt", "anthropic"), "AI 服务", "AI", "🤖"),
    (("adguard", "doubleclick", "googlesyndication", "adsystem"), "广告/统计", "广告", "📢"),
    (("ntp", "pool.ntp", "time.windows", "time.apple"), "时间同步", "系统", "⏱️"),
]

COMPILED = [(tuple(k.lower() for k in keys), name, cat, icon)
            for keys, name, cat, icon in RULES]


def classify(domain):
    """返回 (应用名, 分类, 图标)；未命中返回 (域名, '其他', '🌐')。"""
    d = (domain or "").lower().rstrip(".")
    for keys, name, cat, icon in COMPILED:
        for k in keys:
            if d == k or d.endswith("." + k) or k in d:
                return name, cat, icon
    # 未命中：取主域名展示
    parts = [p for p in d.split(".") if p]
    label = ".".join(parts[-2:]) if len(parts) >= 2 else d
    return (label or "未知"), "其他", "🌐"
