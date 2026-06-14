from .detail_pages import parse_detail_page, parse_fast_draw_detail
from .keno_archive import parse_xoso_keno_archive_page
from .keno_secondary import (
    parse_ketquaday_keno_detail,
    parse_onbit_keno_page,
)
from .list_pages import parse_list_page

__all__ = [
    "parse_detail_page",
    "parse_fast_draw_detail",
    "parse_list_page",
    "parse_ketquaday_keno_detail",
    "parse_onbit_keno_page",
    "parse_xoso_keno_archive_page",
]
