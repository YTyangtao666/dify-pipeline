"""01 商品数据：京东搜索页解析（Playwright 抓取）+ JSON 兜底 + Prompt 构建。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

STYLES = ["ins风明亮", "电商主图白底", "场景生活感"]  # 每商品 3 风格 × 2 张


def parse_jd_html(html: str, keyword: str) -> list[dict]:
    """解析京东搜索结果页 HTML，抽取商品卡片。"""
    soup = BeautifulSoup(html, "lxml")
    products: list[dict] = []
    for item in soup.select("div.gl-item"):
        sku = item.get("data-sku") or ""
        name_el = item.select_one(".p-name em")
        title = (name_el.get_text(" ", strip=True) if name_el else "").strip()
        if not sku or not title:
            continue
        price = None
        price_el = item.select_one(".p-price i[data-price]")
        if price_el:
            m = re.search(r"[\d.]+", price_el.get("data-price", ""))
            if m:
                price = float(m.group())
        shop_el = item.select_one(".p-shop a")
        img_el = item.select_one(".p-img img")
        img = img_el.get("data-lazy-img") or img_el.get("src") or "" if img_el else ""
        link_el = item.select_one(".p-img a")
        link = link_el.get("href", "") if link_el else ""
        products.append({
            "product_id": str(sku),
            "title": title,
            "price": price,
            "shop": shop_el.get_text(strip=True) if shop_el else "",
            "image": _abs_url(img),
            "url": _abs_url(link),
            "keyword": keyword,
        })
    return products


def _abs_url(u: str) -> str:
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return u


def load_products(path: Path) -> list[dict]:
    """兜底：直接加载手工准备的 products.json。"""
    if not path.exists():
        raise FileNotFoundError(f"商品数据文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):  # 容错：{products: [...]} 包装
        data = data.get("products", [])
    for p in data:
        p.setdefault("shop", "")
        p.setdefault("price", None)
        p.setdefault("desc", "")
    return data


def build_gen_prompt(product: dict, style: str) -> str:
    """把商品信息 + 风格编成生图 Prompt。"""
    title = product.get("title", "")
    desc = product.get("desc", "") or ""
    return (
        f"电商商品摄影：{title}。{desc}。风格：{style}，"
        f"构图干净、主体居中突出、细节清晰、专业布光，高清商品图。"
    )


def build_video_script(product: dict) -> dict:
    """为商品生成短视频口播文案 + 预估时长。"""
    title = product.get("title", "")
    desc = product.get("desc", "") or ""
    tts_text = (
        f"大家好，今天给大家带来的是{title}。{desc} "
        f"喜欢的同学点击下方链接了解详情，到手价非常划算！"
    )
    # 中文语速约 4.5 字/秒
    return {"tts_text": tts_text, "duration_est": round(len(tts_text) / 4.5, 1)}


async def scrape_jd(keyword: str, limit: int = 5, headless: bool = True) -> list[dict]:
    """Playwright 打开京东搜索页抓取（真实浏览器渲染后取 HTML）。"""
    from playwright.async_api import async_playwright

    url = f"https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ))
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(2500)  # 等懒加载首屏
        html = await page.content()
        await browser.close()
    products = parse_jd_html(html, keyword=keyword)
    return products[:limit]
