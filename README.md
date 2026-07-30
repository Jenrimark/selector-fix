# 🎯 selector-fix

> 当爬虫选择器失效时，不要猜，去页面里看。

Selenium / Playwright 爬虫 CSS 选择器失效？页面能找到元素但抓不到数据、返回空、或抓到错误内容？`selector-fix` 通过自动化 dump 页面结构，帮你快速定位正确选择器。

## ✨ 功能

- 🔍 **8 维度自动分析** — CSS class、按钮/链接、卡片容器、翻页元素、遮挡层，一次 dump 全拿到
- 📸 **截图 + HTML 存档** — 页面长什么样、DOM 结构是什么，事后离线分析
- 🛡️ **三层点击防御** — 原生 click → JS 强制 → 直接 URL 导航，解决"元素存在但点不到"
- 📋 **实战验证清单** — 不只看"不报错"，要看数据量对不对

## 🚀 快速开始

### 安装依赖

```bash
pip install selenium
```

### 基础用法

```bash
python scripts/dump_page_structure.py \
  --url "https://example.com/target-page" \
  --output-dir ./debug_output
```

### 常用参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--url` | 目标页面 URL（必填） | `"https://noon.com/..."` |
| `--output-dir` | 输出目录 | `./debug_output` |
| `--profile` | Chrome 用户数据目录（复用登录态） | `"C:\Users\you\AppData\..."` |
| `--auto` | 跳过手动登录等待，自动等 8 秒 | |
| `--headless` | 无头模式运行 | |

### 输出文件

```
debug_output/
├── structure_{page}.txt    # 8 维度结构分析报告
├── source_{page}.html      # 完整 page_source
└── screenshot_{page}.png   # 页面截图
```

## 🔧 何时使用

| ✅ 用它 | ❌ 别用 |
|---------|---------|
| "未找到 XX 按钮" | 网络超时 / 连接失败 |
| 抓到 0 条数据 | 账号登录失败 |
| 抓到错误内容（促销语当评分） | 被风控封 IP |
| 翻页失败只能看第一页 | 验证码拦截 |
| 网站改版后爬虫全面失效 | |

## 📖 工作流程

```
1. 确认症状  →  从日志定位失败层（定位？提取？导航？）
2. 创建 Dump  →  用和爬虫相同的浏览器环境，只做观察
3. 运行 Dump  →  先目标页面，再关联页面（如评论页）
4. 分析输出  →  截图 → 遮挡层 → 按钮 → 卡片 → 翻页
5. 修复选择器 →  用 class 稳定前缀，不写死 hash
6. 端到端验证  →  数据量对才算成功
```

## 💡 选择器设计原则

```python
# ✅ 好 — 用 class 稳定前缀
"review_card": "[class*='_noonReviewItem_']"

# ✅ 好 — 用语义属性，不随 CSS 编译变化
"pagination_next": "a[aria-label='Next page']:not([aria-disabled='true'])"

# ❌ 坏 — 写死 hash，CSS 重新编译后失效
"review_card": "[class*='_noonReviewItem_1oceu_29']"

# ❌ 坏 — 太宽泛，匹配到一堆不相关的元素
"rating_avg": "[class*='_skeletonWrapper_uaefh']"
```

## 📂 项目结构

```
selector-fix/
├── SKILL.md                        # 完整调试方法论（8 维度 + 思维流程）
├── scripts/
│   └── dump_page_structure.py      # 通用 dump 工具
└── references/
    └── noon-case-study.md          # 实战案例：Noon 评论爬虫修复
```

## 🧰 依赖

- Python 3.8+
- Selenium 4.x
- Chrome / ChromeDriver

## 📝 License

MIT
