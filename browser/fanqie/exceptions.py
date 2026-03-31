"""番茄小说自定义异常"""


class FanqieException(Exception):
    """番茄小说操作基础异常"""
    pass


class SessionExpiredException(FanqieException):
    """Session过期异常"""
    pass


class PublishFailedException(FanqieException):
    """发布失败异常"""
    pass


class SelectorNotFoundException(FanqieException):
    """选择器未找到异常"""
    pass


class ChapterTooShortException(FanqieException):
    """章节字数不足异常"""
    pass


class BookNotFoundException(FanqieException):
    """书籍未找到异常"""
    pass
