from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

BASE_URL = "https://vietlott.vn"


class ParserKind(StrEnum):
    MATRIX = "matrix"
    THREE_DIGIT = "three_digit"
    FOUR_DIGIT = "four_digit"
    KENO = "keno"
    BINGO = "bingo"


class AjaxKind(StrEnum):
    MATRIX = "matrix"
    THREE_DIGIT = "three_digit"
    FOUR_DIGIT = "four_digit"
    KENO = "keno"
    BINGO = "bingo"


@dataclass(frozen=True, slots=True)
class ProductSpec:
    slug: str
    display_name: str
    list_path: str
    detail_path: str
    ajax_path: str
    parser_kind: ParserKind
    ajax_kind: AjaxKind
    page_size: int
    main_count: int | None = None
    main_min: int | None = None
    main_max: int | None = None
    special_count: int = 0
    special_min: int | None = None
    special_max: int | None = None
    game_id: str | None = None
    array_rows: int | None = None
    array_columns: int | None = None

    @property
    def list_url(self) -> str:
        return f"{BASE_URL}{self.list_path}"

    def detail_url(self, draw_id: str) -> str:
        return f"{BASE_URL}{self.detail_path.format(draw_id=draw_id)}"

    @property
    def ajax_url(self) -> str:
        return f"{BASE_URL}{self.ajax_path}"


PRODUCT_SPECS: dict[str, ProductSpec] = {
    "mega645": ProductSpec(
        slug="mega645",
        display_name="Mega 6/45",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-645",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/645?id={draw_id}&nocatche=1",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.Game645CompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.MATRIX,
        ajax_kind=AjaxKind.MATRIX,
        page_size=8,
        main_count=6,
        main_min=1,
        main_max=45,
        array_rows=6,
        array_columns=18,
    ),
    "power655": ProductSpec(
        slug="power655",
        display_name="Power 6/55",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/655?id={draw_id}&nocatche=1",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.Game655CompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.MATRIX,
        ajax_kind=AjaxKind.MATRIX,
        page_size=8,
        main_count=6,
        main_min=1,
        main_max=55,
        special_count=1,
        special_min=1,
        special_max=55,
        array_rows=5,
        array_columns=18,
    ),
    "lotto535": ProductSpec(
        slug="lotto535",
        display_name="Lotto 5/35",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/535?id={draw_id}&nocatche=1",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.Game535CompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.MATRIX,
        ajax_kind=AjaxKind.MATRIX,
        page_size=8,
        main_count=5,
        main_min=1,
        main_max=35,
        special_count=1,
        special_min=1,
        special_max=12,
        array_rows=5,
        array_columns=35,
    ),
    "max3d": ProductSpec(
        slug="max3d",
        display_name="Max 3D / Max 3D+",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3D",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/max-3D?id={draw_id}&nocatche=1",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DCompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.THREE_DIGIT,
        ajax_kind=AjaxKind.THREE_DIGIT,
        page_size=5,
        game_id="5",
    ),
    "max3dpro": ProductSpec(
        slug="max3dpro",
        display_name="Max 3D Pro",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3Dpro",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/max-3DPro?id={draw_id}&nocatche=1",
        ajax_path=(
            "/ajaxpro/Vietlott.PlugIn.WebParts.GameMax3DProCompareWebPart,Vietlott.PlugIn.WebParts.ashx"
        ),
        parser_kind=ParserKind.THREE_DIGIT,
        ajax_kind=AjaxKind.THREE_DIGIT,
        page_size=5,
        game_id="7",
    ),
    "max4d": ProductSpec(
        slug="max4d",
        display_name="Max 4D (historical)",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-4d",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/max-4d?id={draw_id}&nocatche=1",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.GameMax4DCompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.FOUR_DIGIT,
        ajax_kind=AjaxKind.FOUR_DIGIT,
        page_size=5,
        game_id="2",
    ),
    "keno": ProductSpec(
        slug="keno",
        display_name="Keno",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-keno",
        detail_path="/vi/trung-thuong/ket-qua-trung-thuong/view-detail-keno-result?id={draw_id}",
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.GameKenoCompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.KENO,
        ajax_kind=AjaxKind.KENO,
        page_size=6,
        main_count=20,
        main_min=1,
        main_max=80,
        game_id="6",
    ),
    "bingo18": ProductSpec(
        slug="bingo18",
        display_name="Bingo18",
        list_path="/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18",
        detail_path=(
            "/vi/trung-thuong/ket-qua-trung-thuong/view-detail-bingo18-result?nocatche=1&id={draw_id}"
        ),
        ajax_path=("/ajaxpro/Vietlott.PlugIn.WebParts.GameBingoCompareWebPart,Vietlott.PlugIn.WebParts.ashx"),
        parser_kind=ParserKind.BINGO,
        ajax_kind=AjaxKind.BINGO,
        page_size=6,
        main_count=3,
        main_min=0,
        main_max=9,
        game_id="8",
    ),
}


def resolve_products(values: list[str]) -> list[ProductSpec]:
    if not values or values == ["all"] or "all" in values:
        return list(PRODUCT_SPECS.values())
    unknown = sorted(set(values) - PRODUCT_SPECS.keys())
    if unknown:
        raise ValueError(f"Unknown product(s): {', '.join(unknown)}")
    return [PRODUCT_SPECS[value] for value in values]
