from collections import namedtuple
from contextlib import contextmanager, ExitStack

import sublime

from .runtime import text_command


MYPY = False
if MYPY:
    from typing import Callable, ContextManager, Iterator, List, NamedTuple, Optional
    WrapperFn = Callable[[sublime.View], ContextManager[None]]

    from .types import Row, Col
    Position = NamedTuple("Position", [("row", Row), ("col", Col), ("offset", Optional[float])])

else:
    Position = namedtuple("Position", "row col offset")


def capture_cur_position(view):
    # type: (sublime.View) -> Optional[Position]
    try:
        sel = view.sel()[0]
    except Exception:
        return None

    row, col = view.rowcol(sel.begin())
    return Position(row, col, row_offset(view, sel.begin()))


def row_offset(view, cursor):
    # type: (sublime.View, int) -> float
    _, cy = view.text_to_layout(cursor)
    _, vy = view.viewport_position()
    return (cy - vy) / view.line_height()


# `replace_view_content` is a wrapper for `_replace_region` to get some
# typing support from mypy.
def replace_view_content(view, text, region=None, wrappers=[]):
    # type: (sublime.View, str, sublime.Region, List[WrapperFn]) -> None
    """Replace the content of the view

    If no region is given the whole content will get replaced. Otherwise
    only the selected region.
    """
    _replace_region(view, text, region, wrappers)  # type: ignore[arg-type]


@text_command
def _replace_region(view, edit, text, region=None, wrappers=[]):
    # type: (sublime.View, sublime.Edit, str, sublime.Region, List[WrapperFn]) -> None
    if region is None:
        # If you "replace" (or expand) directly at the cursor,
        # the cursor expands into a selection.
        # This is a common case for an empty view so we take
        # care of it out of box.
        region = sublime.Region(0, max(1, view.size()))

    wrappers = wrappers[:] + [stable_viewport]
    if any(
        region.contains(s) or region.intersects(s)
        for s in view.sel()
    ):
        wrappers += [restore_cursors]

    with ExitStack() as stack:
        for wrapper in wrappers:
            stack.enter_context(wrapper(view))
        stack.enter_context(writable_view(view))
        view.replace(edit, region, text)


@contextmanager
def writable_view(view):
    # type: (sublime.View) -> Iterator[None]
    is_read_only = view.is_read_only()
    view.set_read_only(False)
    try:
        yield
    finally:
        view.set_read_only(is_read_only)


@contextmanager
def restore_cursors(view):
    # type: (sublime.View) -> Iterator[None]
    save_cursors = [
        (view.rowcol(s.begin()), view.rowcol(s.end()))
        for s in view.sel()
    ] or [((0, 0), (0, 0))]

    try:
        yield
    finally:
        view.sel().clear()
        for (begin, end) in save_cursors:
            view.sel().add(
                sublime.Region(view.text_point(*begin), view.text_point(*end))
            )


@contextmanager
def stable_viewport(view):
    # type: (sublime.View) -> Iterator[None]
    # Ref: https://github.com/SublimeTextIssues/Core/issues/2560
    # See https://github.com/jonlabelle/SublimeJsPrettier/pull/171/files
    # for workaround.
    vx, vy = view.viewport_position()
    try:
        yield
    finally:
        view.set_viewport_position((0, 0), animate=False)  # intentional!
        view.set_viewport_position((vx, vy), animate=False)
