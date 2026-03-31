"""
番茄小说后台 CSS/XPath 选择器集中管理

注意：番茄小说为SPA应用，前端可能随时更新。
如果选择器失效，只需修改此文件即可。
实际选择器需要登录后通过浏览器DevTools检查确认。
"""


class LoginPage:
    """登录页选择器"""
    PAGE_URL = "https://fanqienovel.com/writer"
    # 登录页标识
    LOGIN_CONTAINER = ".login-container, .login-wrapper, [class*='login']"


class BookManagePage:
    """书籍管理页选择器"""
    PAGE_URL = "https://fanqienovel.com/main/writer/book-manage"
    # 书籍列表容器
    BOOK_LIST = ".book-list, .work-list, [class*='book-list']"
    # 单个书籍项
    BOOK_ITEM = ".book-item, .work-item, [class*='book-item']"
    # 书籍名称
    BOOK_NAME = ".book-name, .work-name, [class*='book-name'], [class*='title']"
    # 创建新书按钮
    CREATE_BOOK_BTN = ".create-btn, [class*='create'], button:has-text('创建作品')"
    # 书籍链接（进入章节管理）
    BOOK_LINK = "a[href*='book-manage/'], a[href*='chapter']"


class ChapterManagePage:
    """章节管理页选择器"""
    # 新建章节按钮
    NEW_CHAPTER_BTN = "button:has-text('新建章节'), button:has-text('新建草稿'), button:has-text('新建'), [class*='new-chapter'], [class*='create-chapter']"
    # 章节列表
    CHAPTER_LIST = ".chapter-list, [class*='chapter-list'], .chapter-table, [class*='chapter-table'], [class*='chapter-content']"
    # 章节项
    CHAPTER_ITEM = ".chapter-item, [class*='chapter-item'], tr[class*='chapter'], [class*='chapter-row']"
    # 章节状态
    CHAPTER_STATUS = ".chapter-status, [class*='status'], [class*='audit']"
    # 章节标题（在列表中）
    CHAPTER_TITLE_IN_LIST = ".chapter-title, [class*='title'], [class*='chapter-title'], td[class*='title']"
    # 章节号（在列表中）
    CHAPTER_NUM_IN_LIST = ".chapter-num, [class*='num'], [class*='number'], td[class*='num']"


class ChapterEditor:
    """章节编辑器选择器"""
    # 章节标题输入框 - 新版番茄小说placeholder是"请输入章节标题"
    TITLE_INPUT = (
        "input[placeholder*='章节标题'], "
        "input[placeholder*='章节'], "
        "input[placeholder*='标题'], "
        "input[placeholder*='title'], "
        "input[placeholder*='请输入'], "
        "input.input-title, "
        ".chapter-title input, "
        "[class*='title'] input, "
        "input[name*='title']"
    )
    # 内容编辑器 - 先点击"添加正文"按钮出现
    CONTENT_EDITOR = (
        ".ql-editor, "
        ".ProseMirror, "
        "[contenteditable='true'], "
        ".editor-content, "
        "textarea[class*='content'], "
        ".content-editor, "
        "[class*='editor'], "
        ".add-content-editor"
    )
    # 添加正文按钮（弹窗中需要先点击这个才能输入内容）
    ADD_CONTENT_BTN = (
        "button:has-text('添加正文'), "
        "button:has-text('添加内容'), "
        "[class*='add-content'], "
        "[class*='addContent']"
    )
    # 下一步按钮
    NEXT_BTN = (
        "button:has-text('下一步'), "
        "button:has-text('发布'), "
        "[class*='next-btn'], "
        "[class*='submit'], "
        "button.btn-primary"
    )
    # 确定/确认按钮
    CONFIRM_BTN = (
        "button:has-text('确定'), "
        "button:has-text('确认'), "
        "button:has-text('发布'), "
        "[class*='confirm'], "
        "button.btn-primary"
    )
    # 字数统计
    WORD_COUNT = ".word-count, [class*='word-count'], [class*='char-count']"


class PublishDialog:
    """发布对话框选择器"""
    # 立即发布选项 - 扩展选择器
    PUBLISH_NOW = "button:has-text('立即发布'), label:has-text('立即发布'), [class*='publish-now'], .publish-type button, [class*='publish'] button, button.btn-publish, .btn-immediate"
    # 定时发布选项
    PUBLISH_SCHEDULED = "label:has-text('定时发布'), input[value*='schedule'], [class*='publish-schedule']"
    # 定时发布时间选择器
    SCHEDULE_DATETIME = "input[type='datetime-local'], .datetime-picker, [class*='date-picker']"
    # 确认发布按钮 - 扩展选择器
    CONFIRM_BTN = "button:has-text('确认'), button:has-text('发布'), button:has-text('提交审核'), button:has-text('提交'), [class*='confirm-btn'], .submit-btn, button.btn-primary, button[type='submit']"
    # 发布成功提示
    SUCCESS_TOAST = ".toast-success, [class*='success'], .message-success"


class Common:
    """通用选择器"""
    # 加载中
    LOADING = ".loading, [class*='loading'], [class*='spinner']"
    # 错误提示
    ERROR_TOAST = ".toast-error, [class*='error'], .message-error"
    # 模态框
    MODAL = ".modal, [class*='modal'], [class*='dialog']"
    # 关闭按钮
    CLOSE_BTN = ".close, [class*='close'], button:has-text('关闭'), button:has-text('取消')"
    # 下一步按钮
    NEXT_BTN = "button:has-text('下一步'), button:has-text('下一步（审核快）'), [class*='next-btn'], .btn-next"
    # 提交审核按钮 - 扩展选择器
    SUBMIT_BTN = "button:has-text('提交审核'), button:has-text('提交'), button:has-text('发布'), [class*='submit-btn'], [class*='submit'], button.btn-primary, button[type='submit']"

    # 教程弹窗关闭按钮
    TUTORIAL_CLOSE = (
        "button:has-text('知道了'), "
        "button:has-text('我知道了'), "
        "button:has-text('跳过'), "
        "button:has-text('不再显示'), "
        "button:has-text('下一步'), "
        "[class*='tutorial'] button, "
        "[class*='guide'] button, "
        "[class*='close'], "
        "[aria-label='关闭'], "
        ".close-icon"
    )
