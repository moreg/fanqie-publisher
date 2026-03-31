#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深入调试：查找输入框到底在哪里
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def deep_debug():
    print("="*70)
    print("深入调试：查找输入框")
    print("="*70)

    db = get_session()
    book = db.query(Book).filter(Book.book_name.like('%闺蜜%')).first()
    db.close()

    account_lock = await browser_manager.async_get_account_lock(1)
    async with account_lock:
        context = await browser_manager._async_create_context_from_session(1)
        page = await context.new_page()

        try:
            # 导航
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

            # 点击新建章节
            btn = await page.wait_for_selector("button:has-text('新建章节')")
            await btn.click()
            print("[OK] 点击新建章节，等待加载...")
            await asyncio.sleep(5)  # 等待更长时间

            # 截图
            await page.screenshot(path="debug/deep1_drawer.png")
            print("[截图] 抽屉已加载")

            # 详细打印页面结构
            print("\n" + "-"*70)
            print("1. 检查 Shadow DOM:")
            print("-"*70)
            shadow_result = await page.evaluate("""
                () => {
                    const results = [];
                    // 检查所有元素
                    document.querySelectorAll('*').forEach((el, i) => {
                        if (el.shadowRoot) {
                            results.push({tag: el.tagName, index: i, hasShadow: true});
                        }
                    });
                    return results;
                }
            """)
            print(f"   有Shadow DOM的元素: {shadow_result}")

            print("\n" + "-"*70)
            print("2. 检查所有 div 的 class:")
            print("-"*70)
            div_classes = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('div').forEach((el, i) => {
                        if (el.className && el.className.includes('arco')) {
                            results.push({
                                class: el.className.substring(0, 100),
                                visible: el.offsetParent !== null
                            });
                        }
                    });
                    return results;
                }
            """)
            for d in div_classes[:10]:
                print(f"   {d}")

            print("\n" + "-"*70)
            print("3. 检查所有 input:")
            print("-"*70)
            inputs = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('input').forEach((el, i) => {
                        results.push({
                            index: i,
                            tag: 'input',
                            placeholder: el.placeholder,
                            type: el.type,
                            className: el.className.substring(0, 80),
                            id: el.id,
                            name: el.name,
                            visible: el.offsetParent !== null,
                            boundingRect: el.getBoundingClientRect ? JSON.stringify(el.getBoundingClientRect()) : null
                        });
                    });
                    return results;
                }
            """)
            print(f"   共找到 {len(inputs)} 个 input:")
            for inp in inputs:
                print(f"   {inp}")

            print("\n" + "-"*70)
            print("4. 使用 XPath 查找包含 '请输入' 的元素:")
            print("-"*70)
            xpath_result = await page.evaluate("""
                () => {
                    const results = [];
                    const treeWalker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_ELEMENT,
                        null
                    );
                    let node;
                    while(node = treeWalker.nextNode()) {
                        const text = node.textContent || '';
                        if (text.includes('请输入') || text.includes('章节标题')) {
                            results.push({
                                tag: node.tagName,
                                className: node.className ? node.className.substring(0, 80) : '',
                                text: text.substring(0, 50),
                                hasInput: !!node.querySelector('input'),
                                id: node.id
                            });
                        }
                    }
                    return results;
                }
            """)
            for r in xpath_result:
                print(f"   {r}")

            print("\n" + "-"*70)
            print("5. 查找类名包含 'input' 的元素:")
            print("-"*70)
            input_elements = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('[class*="input"], [class*="Input"]').forEach((el, i) => {
                        results.push({
                            tag: el.tagName,
                            className: el.className.substring(0, 100),
                            visible: el.offsetParent !== null,
                            hasInput: !!el.querySelector('input')
                        });
                    });
                    return results;
                }
            """)
            for el in input_elements[:10]:
                print(f"   {el}")

            print("\n" + "-"*70)
            print("6. 直接打印 body 的前20个子元素:")
            print("-"*70)
            body_children = await page.evaluate("""
                () => {
                    const results = [];
                    document.body.childNodes.forEach((el, i) => {
                        if (el.tagName) {
                            results.push({
                                index: i,
                                tag: el.tagName,
                                className: el.className ? el.className.substring(0, 60) : '',
                                id: el.id
                            });
                        }
                    });
                    return results;
                }
            """)
            for c in body_children[:20]:
                print(f"   {c}")

            print("\n" + "="*70)
            print("调试完成")

        finally:
            await page.close()
            await context.close()


if __name__ == "__main__":
    asyncio.run(deep_debug())
