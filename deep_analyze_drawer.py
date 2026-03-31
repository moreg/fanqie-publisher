#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深入分析页面结构 - 实时监控抽屉内容
"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def deep_analyze():
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
        print("2. 等待抽屉完全打开（确保看到输入框）")
        print("3. 按回车继续...")
        print("="*70)

        # 等待用户操作
        print("等待中... (90秒后自动继续)")
        await asyncio.sleep(90)

        print("\n正在深度分析页面结构...\n")

        # 截图
        await page.screenshot(path="debug/deep_analyze.png")

        # 1. 首先尝试点击"添加正文"按钮（如果有的话）
        print("=== 尝试点击'添加正文'按钮 ===")
        try:
            add_btn = await page.wait_for_selector("button:has-text('添加正文')", timeout=3000)
            if add_btn:
                await add_btn.click()
                print("已点击'添加正文'按钮")
                await asyncio.sleep(2)
        except Exception as e:
            print(f"点击'添加正文'失败: {e}")

        # 2. 检查所有可能的输入元素（包括隐藏的）
        print("\n=== 检查所有输入元素 ===")
        all_inputs = await page.evaluate("""
            () => {
                const results = [];

                // 1. 所有input（包括隐藏的）
                document.querySelectorAll('input').forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: results.length,
                        tag: 'INPUT',
                        type: el.type || 'text',
                        placeholder: String(el.placeholder || ''),
                        className: String(el.className || ''),
                        id: String(el.id || ''),
                        name: String(el.name || ''),
                        visible: el.offsetParent !== null,
                        display: getComputedStyle(el).display,
                        visibility: getComputedStyle(el).visibility,
                        rect: rect.width + 'x' + rect.height + ' at ' + rect.left + ',' + rect.top
                    });
                });

                // 2. 所有textarea（包括隐藏的）
                document.querySelectorAll('textarea').forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: results.length,
                        tag: 'TEXTAREA',
                        placeholder: String(el.placeholder || ''),
                        className: String(el.className || ''),
                        id: String(el.id || ''),
                        visible: el.offsetParent !== null,
                        display: getComputedStyle(el).display,
                        visibility: getComputedStyle(el).visibility,
                        rect: rect.width + 'x' + rect.height + ' at ' + rect.left + ',' + rect.top
                    });
                });

                // 3. 所有contentEditable（包括隐藏的）
                document.querySelectorAll('[contenteditable]').forEach((el, i) => {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        index: results.length,
                        tag: String(el.tagName),
                        contenteditable: String(el.getAttribute('contenteditable') || ''),
                        className: String(el.className || ''),
                        visible: el.offsetParent !== null,
                        display: getComputedStyle(el).display,
                        visibility: getComputedStyle(el).visibility,
                        rect: rect.width + 'x' + rect.height + ' at ' + rect.left + ',' + rect.top
                    });
                });

                return results;
            }
        """)
        print(f"共找到 {len(all_inputs)} 个输入元素:")
        for inp in all_inputs:
            print(f"  [{inp['index']}] {inp['tag']} placeholder='{inp['placeholder']}'")
            print(f"      visible={inp['visible']} display={inp['display']} visibility={inp['visibility']}")
            print(f"      class='{inp['className'][:80]}'")
            print(f"      rect={inp['rect']}")

        # 3. 查找包含"章节标题"文本的元素
        print("\n=== 查找'章节标题'附近的所有元素 ===")
        near_title = await page.evaluate("""
            () => {
                const results = [];
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_ELEMENT,
                    null
                );
                let node;
                while(node = walker.nextNode()) {
                    const text = (node.textContent || '').trim();
                    if (text.includes('章节标题') || text.includes('请输入')) {
                        // 获取父元素
                        let parent = node.parentElement;
                        let path = node.tagName;
                        for (let i = 0; i < 5 && parent; i++) {
                            path = parent.tagName + ' > ' + path;
                            parent = parent.parentElement;
                        }

                        results.push({
                            tag: node.tagName,
                            text: text.substring(0, 100),
                            className: String(node.className || ''),
                            path: path
                        });
                    }
                }
                return results;
            }
        """)
        print(f"共找到 {len(near_title)} 个包含'章节标题/请输入'的元素:")
        for el in near_title:
            print(f"  {el['tag']} text='{el['text']}'")
            print(f"      class='{el['className'][:60]}'")
            print(f"      path: {el['path']}")

        # 4. 查找抽屉/弹窗内的所有元素
        print("\n=== 查找抽屉/弹窗内的所有元素 ===")
        drawer_elements = await page.evaluate("""
            () => {
                const results = [];
                // 查找所有可能的容器
                const containers = document.querySelectorAll(
                    '[class*="drawer"], [class*="Drawer"], [class*="modal"], [class*="Modal"], ' +
                    '[class*="popup"], [class*="Popup"], [role="dialog"], ' +
                    '.arco-modal, .arco-drawer, .arco-dialog, .arco-popup'
                );

                containers.forEach((container, ci) => {
                    const rect = container.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const children = [];
                        container.querySelectorAll('*').forEach((el, i) => {
                            if (i < 30) { // 限制每个容器的子元素数量
                                children.push({
                                    tag: el.tagName,
                                    className: String(el.className || '').substring(0, 60),
                                    text: (el.textContent || '').trim().substring(0, 30)
                                });
                            }
                        });
                        results.push({
                            containerClass: String(container.className || '').substring(0, 60),
                            rect: rect.width + 'x' + rect.height,
                            children: children
                        });
                    }
                });
                return results;
            }
        """)
        print(f"共找到 {len(drawer_elements)} 个可见容器:")
        for container in drawer_elements:
            print(f"  容器: class='{container['containerClass']}' size={container['rect']}")
            for child in container['children'][:10]:
                print(f"    {child['tag']} class='{child['className']}' text='{child['text']}'")

        # 5. 检查所有arco-input相关元素
        print("\n=== 检查所有arco-input相关元素 ===")
        arco_inputs = await page.evaluate("""
            () => {
                const results = [];
                // 查找所有arco-input相关元素
                const selectors = [
                    '.arco-input',
                    '[class*="arco-input"]',
                    '.arco-textarea',
                    '[class*="arco-textarea"]',
                    '.arco-input-wrapper',
                    '[class*="input-wrapper"]'
                ];

                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    els.forEach((el, i) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0) {
                            results.push({
                                selector: sel,
                                tag: el.tagName,
                                className: String(el.className || ''),
                                visible: rect.width + 'x' + rect.height,
                                // 查找内部input
                                innerInput: el.querySelector('input') ? {
                                    placeholder: String(el.querySelector('input').placeholder || ''),
                                    value: String(el.querySelector('input').value || '').substring(0, 50)
                                } : null
                            });
                        }
                    });
                }
                return results;
            }
        """)
        print(f"共找到 {len(arco_inputs)} 个arco-input相关元素:")
        for el in arco_inputs:
            print(f"  {el['selector']} class='{el['className'][:60]}' visible={el['visible']}")
            if el['innerInput']:
                print(f"    innerInput: placeholder='{el['innerInput']['placeholder']}'")

        # 6. 尝试使用JavaScript点击标题输入框并输入
        print("\n=== 尝试用JavaScript操作输入框 ===")
        js_result = await page.evaluate("""
            () => {
                // 查找所有可能的输入框
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {
                    const rect = inp.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        // 尝试触发focus
                        inp.focus();
                        return {
                            found: true,
                            placeholder: String(inp.placeholder || ''),
                            className: String(inp.className || ''),
                            rect: rect.width + 'x' + rect.height,
                            documentActiveElement: document.activeElement?.tagName || 'none'
                        };
                    }
                }

                // 查找arco-input内部的input
                const arcoInputs = document.querySelectorAll('.arco-input, [class*="arco-input"]');
                for (const wrapper of arcoInputs) {
                    const rect = wrapper.getBoundingClientRect();
                    if (rect.width > 0) {
                        const input = wrapper.querySelector('input');
                        if (input) {
                            input.focus();
                            return {
                                found: true,
                                type: 'arco-input',
                                placeholder: String(input.placeholder || ''),
                                wrapperClass: String(wrapper.className || '').substring(0, 60),
                                documentActiveElement: document.activeElement?.tagName || 'none'
                            };
                        }
                    }
                }

                return {found: false};
            }
        """)
        print(f"JavaScript查找结果: {js_result}")

        print("\n" + "="*70)
        print("截图已保存到 debug/deep_analyze.png")
        print("="*70)

        await page.close()
        await context.close()


if __name__ == "__main__":
    asyncio.run(deep_analyze())
