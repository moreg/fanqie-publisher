#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
等待用户手动打开抽屉后，分析页面结构
"""
import asyncio
import sys
import time
sys.stdout.reconfigure(encoding='utf-8')

from browser.manager import browser_manager
from database.connection import get_session
from database.models import Book


async def wait_for_drawer():
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
        print("3. 确认能看到'章节标题'输入框和'正文'输入区域")
        print("4. 然后回到这个窗口按回车键...")
        print("="*70 + "\n")

        # 等待30秒让用户操作
        print("等待中... (30秒后自动继续)")
        await asyncio.sleep(30)

        print("正在分析页面结构...\n")

        # 截图
        await page.screenshot(path="debug/user_opened_drawer.png")

        # 分析所有输入元素
        print("=== 分析所有 input 元素 ===")
        inputs = await page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('input').forEach((el, i) => {
                    results.push({
                        index: i,
                        tag: 'INPUT',
                        placeholder: String(el.placeholder || ''),
                        type: String(el.type || 'text'),
                        className: String(el.className || ''),
                        id: String(el.id || ''),
                        name: String(el.name || ''),
                        disabled: el.disabled,
                        readOnly: el.readOnly,
                        rect: el.getBoundingClientRect ? JSON.stringify(el.getBoundingClientRect()) : 'N/A'
                    });
                });
                return results;
            }
        """)
        print(f"共找到 {len(inputs)} 个 input:")
        for inp in inputs:
            print(f"  [{inp['index']}] placeholder='{inp['placeholder']}' type={inp['type']} class='{inp['className'][:60]}' disabled={inp['disabled']}")

        print("\n=== 分析所有 textarea 元素 ===")
        textareas = await page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('textarea').forEach((el, i) => {
                    results.push({
                        index: i,
                        tag: 'TEXTAREA',
                        placeholder: String(el.placeholder || ''),
                        className: String(el.className || ''),
                        disabled: el.disabled,
                        rect: el.getBoundingClientRect ? JSON.stringify(el.getBoundingClientRect()) : 'N/A'
                    });
                });
                return results;
            }
        """)
        print(f"共找到 {len(textareas)} 个 textarea:")
        for ta in textareas:
            print(f"  [{ta['index']}] placeholder='{ta['placeholder']}' class='{ta['className'][:60]}' disabled={ta['disabled']}")

        print("\n=== 分析所有 contentEditable 元素 ===")
        contenteditable = await page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('[contenteditable]').forEach((el, i) => {
                    results.push({
                        index: i,
                        tag: String(el.tagName || ''),
                        contenteditable: String(el.getAttribute('contenteditable') || ''),
                        className: String(el.className || ''),
                        rect: el.getBoundingClientRect ? JSON.stringify(el.getBoundingClientRect()) : 'N/A'
                    });
                });
                return results;
            }
        """)
        print(f"共找到 {len(contenteditable)} 个 contentEditable:")
        for ce in contenteditable:
            print(f"  [{ce['index']}] {ce['tag']} contenteditable={ce['contenteditable']} class='{ce['className'][:60]}'")

        print("\n=== 分析页面可见文本 ===")
        texts = await page.evaluate("""
            () => {
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    null
                );
                const texts = [];
                let node;
                while(node = walker.nextNode()) {
                    const text = (node.textContent || '').trim();
                    if (text && text.length > 0 && text.length < 100) {
                        texts.push(text);
                    }
                }
                return texts;
            }
        """)
        print("页面可见文本:")
        for t in texts:
            print(f"  '{t}'")

        print("\n" + "="*70)
        print("截图已保存到 debug/user_opened_drawer.png")
        print("请将截图发给我，我来分析页面结构")
        print("="*70)

        await page.close()
        await context.close()


if __name__ == "__main__":
    asyncio.run(wait_for_drawer())
