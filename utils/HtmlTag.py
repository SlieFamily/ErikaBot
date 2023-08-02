import re
from pyquery import PyQuery as Pq
from yarl import URL
from html import unescape as html_unescape

def handle_lists(html: Pq, html_str: str) -> str:
    # 有序/无序列表 标签处理
    for ul in html("ul").items():
        for li in ul("li").items():
            li_str_search = re.search("<li>(.+)</li>", repr(str(li)))
            html_str = html_str.replace(
                str(li), f"\n- {li_str_search[1]}"  # type: ignore
            ).replace("\\n", "\n")
    for ol in html("ol").items():
        for index, li in enumerate(ol("li").items()):
            li_str_search = re.search("<li>(.+)</li>", repr(str(li)))
            html_str = html_str.replace(
                str(li), f"\n{index + 1}. {li_str_search[1]}"  # type: ignore
            ).replace("\\n", "\n")
    html_str = re.sub("</(ul|ol)>", "\n", html_str)
    # 处理没有被 ul / ol 标签包围的 li 标签
    html_str = html_str.replace("<li>", "- ").replace("</li>", "")
    return html_str


# <a> 标签处理
def handle_links(html: Pq, html_str: str) -> str:
    for a in html("a").items():
        a_str = re.search(
            r"<a [^>]+>.*?</a>", html_unescape(str(a)), flags=re.DOTALL
        ).group()  # type: ignore
        if a.text() and str(a.text()) != a.attr("href"):
            # 去除微博超话
            if re.search(
                r"https://m\.weibo\.cn/p/index\?extparam=\S+&containerid=\w+",
                a.attr("href"),
            ):
                html_str = html_str.replace(a_str, "")
            # 去除微博话题对应链接 及 微博用户主页链接，只保留文本
            elif (
                a.attr("href").startswith("https://m.weibo.cn/search?containerid=")
                and re.search("#.+#", a.text())
            ) or (
                a.attr("href").startswith("https://weibo.com/")
                and a.text().startswith("@")
            ):
                html_str = html_str.replace(a_str, a.text())
            else:
                if a.attr("href").startswith("https://weibo.cn/sinaurl?u="):
                    a.attr("href", URL(a.attr("href")).query["u"])
                html_str = html_str.replace(a_str, f" {a.text()}: {a.attr('href')}\n")
        else:
            html_str = html_str.replace(a_str, f" {a.attr('href')}\n")
    return html_str


# HTML标签等处理
def handle_html_tag(html: Pq) -> str:
    html_str = html_unescape(str(html))

    html_str = handle_lists(html, html_str)
    html_str = handle_links(html, html_str)

    # 处理一些 HTML 标签
    html_tags = [
        "b",
        "blockquote",
        "code",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "figure",
        "font",
        "i",
        "iframe",
        "ol",
        "p",
        "pre",
        "s",
        "small",
        "span",
        "strong",
        "sub",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    ]

    # <p> <pre> 标签后增加俩个换行
    for i in ["p", "pre"]:
        html_str = re.sub(f"</{i}>", f"</{i}>\n\n", html_str)

    # 直接去掉标签，留下内部文本信息
    for i in html_tags:
        html_str = re.sub(f"<{i} [^>]+>", "", html_str)
        html_str = re.sub(f"</?{i}>", "", html_str)

    html_str = re.sub(r"<(br|hr)\s?/?>|<(br|hr) [^>]+>", "\n", html_str)
    html_str = re.sub(r"<h\d [^>]+>", "\n", html_str)
    html_str = re.sub(r"</?h\d>", "\n", html_str)

    # 删除图片、视频标签
    html_str = re.sub(
        r"<video[^>]*>(.*?</video>)?|<img[^>]+>", "", html_str, flags=re.DOTALL
    )

    # 去掉多余换行
    while "\n\n\n" in html_str:
        html_str = html_str.replace("\n\n\n", "\n\n")
    html_str = html_str.strip()

    return html_str
