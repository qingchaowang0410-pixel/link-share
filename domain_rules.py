from urllib.parse import urlparse

CATEGORIES = [
    "代码/工具",
    "视频",
    "文章/博客",
    "AI 相关",
    "设计",
    "产品",
    "教程",
    "其他",
]

DOMAIN_RULES = {
    # 代码/工具
    "github.com": "代码/工具",
    "gitlab.com": "代码/工具",
    "bitbucket.org": "代码/工具",
    "npmjs.com": "代码/工具",
    "pypi.org": "代码/工具",
    "stackoverflow.com": "代码/工具",
    # 视频
    "youtube.com": "视频",
    "youtu.be": "视频",
    "bilibili.com": "视频",
    "b23.tv": "视频",
    "vimeo.com": "视频",
    # 文章/博客
    "zhihu.com": "文章/博客",
    "zhuanlan.zhihu.com": "文章/博客",
    "medium.com": "文章/博客",
    "juejin.cn": "文章/博客",
    "jianshu.com": "文章/博客",
    "csdn.net": "文章/博客",
    "substack.com": "文章/博客",
    "mp.weixin.qq.com": "文章/博客",
    # AI 相关
    "openai.com": "AI 相关",
    "anthropic.com": "AI 相关",
    "huggingface.co": "AI 相关",
    "arxiv.org": "AI 相关",
    "claude.ai": "AI 相关",
    "chat.openai.com": "AI 相关",
    # 设计
    "dribbble.com": "设计",
    "behance.net": "设计",
    "figma.com": "设计",
    "pinterest.com": "设计",
    # 产品
    "producthunt.com": "产品",
    "indiehackers.com": "产品",
    # 教程
    "coursera.org": "教程",
    "udemy.com": "教程",
    "freecodecamp.org": "教程",
    "w3schools.com": "教程",
    "developer.mozilla.org": "教程",
}


def guess_category(url: str) -> str:
    """根据 URL 域名猜测分类，没命中返回 '其他'。"""
    if not url:
        return "其他"
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "其他"
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]

    if host in DOMAIN_RULES:
        return DOMAIN_RULES[host]

    # 退而求其次：匹配父域名（例如 foo.github.com → github.com）
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in DOMAIN_RULES:
            return DOMAIN_RULES[parent]

    return "其他"
