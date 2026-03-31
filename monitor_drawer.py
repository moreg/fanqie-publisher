#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控抽屉 - 持续检查直到发现输入框
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def monitor_drawer():
    db = get_session()
    book = db.query(Book).filter(Book.book_name.like('%闺蜜%')).first()
    db.close()

    account_lock = await browser_manager.async_get_account_lock(1)
    async with account_lock:
        context = await browser_manager._async_create_context_from_session(1)
        page = await context.new_page()

        await page.goto(f"https://fanqienovel.com/main/writer/chapter-manage/{book.fanqie_book_id}")
        await asyncio.sleep(2)

        # 关闭弹窗
        try:
            btn = await page.wait_for_selector("text=我知道了", timeout=2000)
            if btn:
                await btn.click()
                await asyncio.sleep(1)
        except:
            pass

        print("\n" + "="*70)
        print("请在浏览器中手动操作:")
        print("1. 点击'新建章节'按钮")
        print("2. 等待抽屉完全打开")
        print("3. 按回车继续分析...")
        print("="*70)

        # 等待用户操作
        print("等待中... (按Ctrl+C退出)")
        await asyncio.sleep(120)

        print("\n=== 截图并分析 ===")

        # 立即截图保存当前状态
        await page.screenshot(path="debug/current_state.png")
        print("截图已保存到 debug/current_state.png")

        # 检查页面URL
        print(f"\n当前URL: {page.url}")

        # 检查"请输入章节标题"文本是否存在
        page_text = await page.inner_text("body")
        has_title_hint = "章节标题" in page_text or "请输入章节" in page_text
        print(f"页面包含'章节标题'文本: {has_title_hint}")

        # 如果文本存在但找不到元素，说明元素在特殊容器中
        if has_title_hint:
            print("\n文本存在但DOM查询失败！尝试更深入的分析...")

            # 深度遍历body下所有元素
            deep_analysis = await page.evaluate("""
                () => {
                    const allElements = [];
                    let index = 0;

                    function traverse(root, depth, maxDepth) {
                        if (depth > maxDepth) return;

                        for (const el of root.children) {
                            const rect = el.getBoundingClientRect();
                            allElements.push({
                                index: index++,
                                tag: el.tagName,
                                className: String(el.className || '').substring(0, 80),
                                id: el.id || '',
                                depth: depth,
                                rect: rect.width + 'x' + rect.height,
                                visible: rect.width > 0 && rect.height > 0,
                                text: (el.textContent || '').trim().substring(0, 50)
                            });
                            traverse(el, depth + 1, maxDepth);
                        }
                    }

                    traverse(document.body, 0, 10);
                    return allElements.slice(0, 200); // 限制数量
                }
            """)
            print(f"\n页面共有 {len(deep_analysis)} 个元素")
            for el in deep_analysis[:30]:
                if el['visible']:
                    print(f"  [{el['index']}] {el['tag']} class='{el['className'][:50]}' rect={el['rect']} text='{el['text']}'")

            # 尝试查找包含"章节标题"的元素的完整路径
            print("\n=== 查找包含'章节标题'文本的元素路径 ===")
            title_path = await page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null
                    );
                    const results = [];
                    let node;
                    while(node = walker.nextNode()) {
                        const text = (node.textContent || '').trim();
                        if (text.includes('章节标题') || text.includes('请输入章节')) {
                            let element = node.parentElement;
                            let path = [];
                            for (let i = 0; i < 10 && element; i++) {
                                path.unshift({
                                    tag: element.tagName,
                                    className: String(element.className || '').substring(0, 40)
                                });
                                element = element.parentElement;
                            }
                            results.push({
                                text: text.substring(0, 50),
                                path: path
                            });
                        }
                    }
                    return results;
                }
            """)
            for r in title_path:
                print(f"文本: '{r['text']}'")
                for p in r['path']:
                    print(f"  -> {p['tag']} class='{p['className']}'")

            # 检查#app下的直接子元素
            print("\n=== #app 下的元素结构 ===")
            app_children = await page.evaluate("""
                () => {
                    const app = document.getElementById('app');
                    if (!app) return [];

                    const children = [];
                    function process(el, depth) {
                        if (depth > 3) return;
                        const rect = el.getBoundingClientRect();
                        children.push({
                            tag: el.tagName,
                            className: String(el.className || '').substring(0, 60),
                            depth: depth,
                            rect: rect.width + 'x' + rect.height,
                            visible: rect.width > 0
                        });
                        for (const child of el.children) {
                            process(child, depth + 1);
                        }
                    }
                    process(app, 0);
                    return children;
                }
            """)
            for el in app_children[:50]:
                indent = "  " * el['depth']
                print(f"{indent}{el['tag']} class='{el['className']}' rect={el['rect']}")

        print("\n" + "="*70)
        print("分析完成！")
        print("="*70)

        await page.close()
        await context.close()


if __name__ == "__main__":
    asyncio.run(monitor_drawer())
