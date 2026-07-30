# 实战案例：Noon 评论爬虫选择器修复

## 问题背景

Noon.com 评论爬虫（Selenium）出现三个症状：
1. "未找到 View All 按钮" → 回退到商品页提取
2. 只能抓到 15 条评论（商品页单页容量），无法翻页
3. 平均分数抓到 "BUY 2 TOGETHER FOR 100.00"（促销文本）

## 调试过程还原

### 阶段 1：从日志定位问题层

```
日志 N70125807V：
  评论总数: 189
  [WARNING] 未找到 View All 按钮，尝试直接从商品页提取
  评论数: 15    ← 189 条只抓了 15 条
```

**推理链**：
- `评论总数: 189` → 评论数检测是准的，数据确实存在
- `未找到 View All 按钮` → 选择器 `a[class*='_viewMore_pmj7w']` 找不到元素
- `评论数: 15` → 回退逻辑只抓商品页，而商品页只显示 15 条

**判断**：问题在定位层（选择器失效）+ 导航层（无法跳转到评论页）

### 阶段 2：创建 Dump 脚本

创建了 `debug_review_structure.py`，核心逻辑：

```python
# 用 JS 一次性收集页面所有结构信息
analysis = driver.execute_script("""
    // 1. 找所有带 "review" 的 CSS class
    // 2. 找所有带 "View All" 文字的链接/按钮
    // 3. 找评论卡片容器
    // 4. 找翻页元素
    // 5. 找遮挡层（cookie banner）
""")
```

**关键决策**：不只 dump 当前页面，还要 dump **跳转目标页面**。
- 商品页：`/smart-band-9-active-.../N70125807V/p/` — 有 View All 按钮
- 评论页：`/reviews/N70125807V/` — 有翻页功能

### 阶段 3：分析 Dump 输出

**发现 1 — View All 按钮实际存在**：
```
[3] tag=A  text="View All reviews"
     class="_viewMore_pmj7w_7"
     href="/uae-en/reviews/N70125807V/?o=f01da81d3970facf"
```
选择器 `_viewMore_pmj7w` 能匹配 `_viewMore_pmj7w_7`，所以选择器本身没错。

**发现 2 — Cookie 弹窗遮挡**：
```
[4] tag=BUTTON  text="Accept All"
     class="_button_wrccg_1 _inline_wrccg_16 ..."
```
截图确认：cookie banner 覆盖在页面上方。按钮在 DOM 中存在但被遮挡，Selenium `.click()` 报错。

**发现 3 — 评论页有翻页功能**：
```json
{
  "selector": "a[aria-label=\"Next page\"]",
  "count": 1,
  "html": "<a ... aria-disabled=\"false\" aria-label=\"Next page\" rel=\"next\">..."
}
```
翻页选择器 `a[aria-label='Next page']` 完全正确！只是从未到达评论页。

**发现 4 — 评分选择器太宽泛**：
```
rating_avg 选择器: [class*='_skeletonWrapper_uaefh']
页面上匹配到 50+ 个元素（促销文本、加载占位符都在用这个 class）
```
正确目标是 `_overallRating_y2ubz_1`（只包含 "4.4"）。

### 阶段 4：根因总结

| 症状 | 根因 | 层 |
|------|------|-----|
| View All 找不到 | cookie 弹窗遮挡，click 失败 | 交互层 |
| 只抓 15 条 | 回退到商品页，从未到达评论页 | 逻辑层 |
| 翻页不存在 | 从未到达有翻页功能的评论页 | 逻辑层 |
| 平均分抓到促销文本 | skeletonWrapper 选择器太宽泛 | 选择器层 |
| 评分总数 = "1" | `(\d+)` 正则遇逗号断裂 | 解析层 |

### 阶段 5：修复策略

**View All 点击**：
```python
# 之前：简单 find + click
view_all = driver.find_element(By.CSS_SELECTOR, SELECTORS["view_all_reviews"])
view_all.click()

# 之后：三层防御
# 1. 先关 cookie 弹窗
_dismiss_cookie_banner(driver)
# 2. WebDriverWait 等待按钮可点击
el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(...))
# 3. Selenium click 失败时 JS 兜底，最终 fallback 直接导航
try:
    el.click()
except:
    driver.execute_script("arguments[0].click();", el)
if "/reviews/" not in driver.current_url:
    driver.get(f"https://www.noon.com/uae-en/reviews/{nins}/")
```

**评论总数检测**：
```python
# 之前：商品页读不到就 return []
if total == 0:
    return []

# 之后：商品页读不到就去评论页确认
if total == 0:
    driver.get(f"https://www.noon.com/uae-en/reviews/{nins}/")
    total = _parse_review_count(...)
    if total == 0:
        return []  # 真的没评论
```

**翻页点击**：
```python
# 之前
next_btn.click()

# 之后：JS 强制点击 + 等待新卡片
try:
    next_btn.click()
except:
    driver.execute_script("arguments[0].click();", next_btn)
WebDriverWait(driver, 5).until(lambda d:
    d.find_elements(selector)[0].text[:50] != old_first
)
```

### 阶段 6：验证结果

```
之前: 评论总数 189 → 实际抓取 15 条
之后: 评论总数 189 → 实际抓取 189 条（13 页翻页成功）✅
```

## 思维模式提炼

```
1. 读日志 → 隔离问题层（选择器？交互？逻辑？）
2. 不猜测 → dump 页面看真实结构
3. 不只看目标页面 → 跳转目标页面也要 dump
4. 不只看"能不能找到" → 还要看"有没有遮挡"
5. 不只看"不报错" → 还要看"数据对不对"
6. 三层防御：原生操作 → JS 强制 → 直接导航
7. 验证用大数据量 → 15→189 才算成功
```
