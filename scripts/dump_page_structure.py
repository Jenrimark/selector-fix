"""
通用网页爬虫选择器调试工具（selector-fix）
- 用 Selenium 打开目标页面，dump 全部 CSS 结构到文件
- 支持任意 URL，自动分析 8 个维度的 DOM 结构
- 输出纯文本报告 + page_source HTML + 截图

用法:
  python dump_page_structure.py --url "https://example.com/page" --output-dir ./debug
  python dump_page_structure.py --url "https://example.com/page" --auto   # 跳过登录等待
  python dump_page_structure.py --url "https://example.com/page" --no-login  # 不先打开首页
"""

import argparse
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


# ========== JS 分析脚本 ==========
# 在浏览器中执行，一次性收集所有结构信息
ANALYSIS_JS = """
const result = {};

// 1. 所有包含关键词的 CSS class
const allEls = document.querySelectorAll('*');
const classBuckets = {};
const KEYWORDS = ['review', 'rating', 'paginat', 'page', 'modal', 'cookie', 'banner', 'overlay', 'popup'];
for (const el of allEls) {
    const cls = (typeof el.className === 'string') ? el.className : '';
    if (!cls) continue;
    for (const kw of KEYWORDS) {
        const re = new RegExp(kw, 'i');
        const matching = cls.split(' ').filter(c => re.test(c));
        if (matching.length > 0) {
            if (!classBuckets[kw]) classBuckets[kw] = new Set();
            matching.forEach(c => classBuckets[kw].add(c));
        }
    }
}
result.classBuckets = {};
for (const [kw, set] of Object.entries(classBuckets)) {
    result.classBuckets[kw] = [...set].slice(0, 40);
}

// 2. 按钮/链接：包含关键词的可交互元素
const interactiveInfo = [];
const clickables = document.querySelectorAll('a, button, [role="button"]');
for (const el of clickables) {
    const text = (el.textContent || '').trim();
    const href = el.href || '';
    const cls = el.className || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    if (text.length < 100 && text.length > 0) {
        interactiveInfo.push({
            tag: el.tagName,
            text: text.substring(0, 80),
            href: href.substring(0, 200),
            class: cls.substring(0, 150),
            ariaLabel: ariaLabel,
            outerHTML: el.outerHTML.substring(0, 400)
        });
    }
}
result.interactiveElements = interactiveInfo.slice(0, 50);

// 3. 卡片/列表项：常见容器选择器
const cardSelectors = [
    '[class*="Item"]', '[class*="Card"]', '[class*="Row"]',
    '[class*="item"]', '[class*="card"]', '[class*="row"]',
    '[data-qa*="item"]', '[data-testid*="item"]',
    '[role="listitem"]',
];
result.cardCandidates = [];
for (const sel of cardSelectors) {
    const els = document.querySelectorAll(sel);
    if (els.length >= 2 && els.length <= 200) {
        result.cardCandidates.push({
            selector: sel,
            count: els.length,
            firstHTML: els[0].outerHTML.substring(0, 2000),
            firstClasses: els[0].className,
        });
    }
}

// 4. 分页元素
const paginationSelectors = [
    'a[aria-label*="Next"]', 'a[aria-label*="next"]',
    'button[aria-label*="Next"]', 'button[aria-label*="next"]',
    'a[aria-label*="Page"]', 'a[aria-label*="page"]',
    '[class*="paginat"]', '[class*="Paginat"]',
    '[class*="nextPage"]', '[class*="next-page"]',
    '[class*="loadMore"]', '[class*="load-more"]',
    'a[href*="page="]', 'a[href*="&page"]',
    'a[rel="next"]',
];
result.pagination = [];
for (const sel of paginationSelectors) {
    const els = document.querySelectorAll(sel);
    if (els.length > 0) {
        result.pagination.push({
            selector: sel,
            count: els.length,
            html: [...els].slice(0, 3).map(e => e.outerHTML.substring(0, 400)).join('\\n'),
            text: [...els].slice(0, 3).map(e => e.textContent.trim().substring(0, 50)),
        });
    }
}

// 5. 遮挡层（cookie banner, modal, overlay）
const overlaySelectors = [
    '[class*="cookie"]', '[class*="Cookie"]',
    '[class*="consent"]', '[class*="Consent"]',
    '[class*="banner"]', '[class*="Banner"]',
    '[class*="modal"]', '[class*="Modal"]',
    '[class*="overlay"]', '[class*="Overlay"]',
    '[class*="popup"]', '[class*="Popup"]',
    '[id*="cookie"]', '[id*="consent"]',
];
result.overlays = [];
for (const sel of overlaySelectors) {
    const els = document.querySelectorAll(sel);
    if (els.length > 0) {
        result.overlays.push({
            selector: sel,
            count: els.length,
            visible: [...els].some(e => {
                const style = window.getComputedStyle(e);
                return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
            }),
            text: els[0].textContent.trim().substring(0, 100),
        });
    }
}

// 6. 页面标题和 URL
result.pageTitle = document.title;
result.pageURL = window.location.href;

// 7. body 文本预览
result.bodyPreview = document.body?.textContent?.trim().substring(0, 500) || '';

return result;
"""


def create_driver(profile_dir: str = None, headless: bool = False) -> webdriver.Chrome:
    """创建 Chrome driver"""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    if profile_dir:
        opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--start-maximized")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # 查找便携版 Chrome
    script_dir = os.path.dirname(os.path.abspath(__file__))
    portable = os.path.join(script_dir, "..", "..", "chrome-win64", "chrome.exe")
    if os.path.isfile(portable):
        opts.binary_location = portable

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(3)
    driver.execute_cdp_cmd("Emulation.setPageScaleFactor", {"pageScaleFactor": 0.5})
    return driver


def dump_page(driver, url: str, output_dir: str, label: str = None):
    """打开 URL，分析并 dump 页面结构"""
    if not label:
        # 从 URL 生成标签
        label = url.split("/")[-2] if url.endswith("/") else url.split("/")[-1]
        label = label[:50] if label else "page"

    print(f"\n{'='*60}")
    print(f"[DUMP] {label}")
    print(f"  URL: {url}")
    print(f"{'='*60}")

    driver.get(url)
    time.sleep(5)

    # 等待页面渲染
    for i in range(10):
        try:
            body = driver.find_element(By.TAG_NAME, "body").text.strip()
            if len(body) > 100:
                break
        except Exception:
            pass
        print(f"  Waiting for page load... ({i+1}/10)")
        time.sleep(1)

    # 滚动触发懒加载
    for _ in range(5):
        driver.execute_script("window.scrollBy(0, 600)")
        time.sleep(0.3)
    time.sleep(2)

    # 执行 JS 分析
    try:
        analysis = driver.execute_script(ANALYSIS_JS)
    except Exception as e:
        print(f"  [WARN] JS analysis failed: {e}")
        analysis = {}

    # 写报告
    os.makedirs(output_dir, exist_ok=True)
    report_file = os.path.join(output_dir, f"structure_{label}.txt")

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"Page Structure Analysis\n")
        f.write(f"URL: {url}\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*80}\n\n")

        # 页面基本信息
        f.write(f"[0] Page Info\n")
        f.write(f"  Title: {analysis.get('pageTitle', '?')}\n")
        f.write(f"  Final URL: {analysis.get('pageURL', '?')}\n")
        f.write(f"  Body preview: {analysis.get('bodyPreview', '')[:200]}\n\n")

        # 维度 1: CSS class 分桶
        f.write(f"[1] CSS Classes by keyword\n")
        for kw, classes in analysis.get("classBuckets", {}).items():
            f.write(f"  --- {kw} ({len(classes)} classes) ---\n")
            for cls in classes:
                f.write(f"    {cls}\n")
            f.write(f"\n")

        # 维度 2: 可交互元素
        f.write(f"[2] Interactive elements ({len(analysis.get('interactiveElements', []))})\n")
        for i, el in enumerate(analysis.get("interactiveElements", [])):
            f.write(f"  [{i+1}] <{el['tag']}> text=\"{el['text']}\"\n")
            f.write(f"       class=\"{el['class']}\"\n")
            if el.get("ariaLabel"):
                f.write(f"       aria-label=\"{el['ariaLabel']}\"\n")
            if el.get("href"):
                f.write(f"       href=\"{el['href']}\"\n")
            f.write(f"       HTML: {el['outerHTML'][:200]}\n\n")

        # 维度 3: 卡片候选
        f.write(f"[3] Card/list candidates ({len(analysis.get('cardCandidates', []))})\n")
        for cand in analysis.get("cardCandidates", []):
            f.write(f"  Selector: {cand['selector']}  Count: {cand['count']}\n")
            f.write(f"  First card class: {cand['firstClasses']}\n")
            f.write(f"  First card HTML:\n{cand['firstHTML'][:1000]}\n\n")

        # 维度 4: 分页
        f.write(f"[4] Pagination elements ({len(analysis.get('pagination', []))})\n")
        for p in analysis.get("pagination", []):
            f.write(f"  Selector: {p['selector']}  Count: {p['count']}\n")
            f.write(f"  Text: {p['text']}\n")
            f.write(f"  HTML:\n{p['html'][:500]}\n\n")
        if not analysis.get("pagination"):
            f.write(f"  (No pagination elements found)\n\n")

        # 维度 5: 遮挡层
        f.write(f"[5] Overlays / banners ({len(analysis.get('overlays', []))})\n")
        for ov in analysis.get("overlays", []):
            f.write(f"  Selector: {ov['selector']}  Count: {ov['count']}  Visible: {ov['visible']}\n")
            f.write(f"  Text: {ov['text']}\n\n")
        if not analysis.get("overlays"):
            f.write(f"  (No overlays found)\n\n")

    print(f"  [OK] Report: {report_file}")

    # 保存 page_source
    src_file = os.path.join(output_dir, f"source_{label}.html")
    with open(src_file, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"  [OK] Page source: {src_file}")

    # 截图
    png_file = os.path.join(output_dir, f"screenshot_{label}.png")
    driver.save_screenshot(png_file)
    print(f"  [OK] Screenshot: {png_file}")

    return report_file


def main():
    parser = argparse.ArgumentParser(description="Dump web page structure for selector debugging")
    parser.add_argument("--url", required=True, help="Target URL to analyze")
    parser.add_argument("--output-dir", default="./debug_output", help="Output directory")
    parser.add_argument("--profile", default=None, help="Chrome user data dir (for login cookies)")
    parser.add_argument("--auto", action="store_true", help="Skip login prompt, wait 8s for cookies")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--no-login", action="store_true", help="Don't open login page first")
    args = parser.parse_args()

    driver = create_driver(profile_dir=args.profile, headless=args.headless)

    try:
        if not args.no_login:
            # 打开首页让 cookie 生效
            base = "/".join(args.url.split("/")[:3])
            driver.get(base)
            if args.auto:
                print("[auto] Waiting 8s for session/cookies...")
                time.sleep(8)
            else:
                input("Login in browser if needed, then press Enter >>>")

        dump_page(driver, args.url, args.output_dir)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()

    print(f"\n{'='*60}")
    print(f"Done! Check {args.output_dir}/ for output files.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
