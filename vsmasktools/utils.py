from __future__ import annotations

from typing import Any, Iterable

from vsexprtools import ExprOp, aka_expr_available, norm_expr
from vskernels import Bilinear, Kernel, KernelT
from vsrgtools import box_blur, gauss_blur
from vstools import (
    CustomValueError, FrameRangeN, FrameRangesN, FuncExceptT, check_variable, check_variable_format, flatten,
    get_peak_value, insert_clip, replace_ranges, split, vs, depth
)

from .edge import EdgeDetect, RidgeDetect
from .types import GenericMaskT
from .abstract import GeneralMask

__all__ = [
    'max_planes',

    'region_rel_mask', 'region_abs_mask',

    'squaremask', 'replace_squaremask', 'freeze_replace_squaremask',

    'normalize_mask'
]


def max_planes(*_clips: vs.VideoNode | Iterable[vs.VideoNode], resizer: KernelT = Bilinear) -> vs.VideoNode:
    clips = list[vs.VideoNode](flatten(_clips))  # type: ignore

    assert check_variable_format((model := clips[0]), max_planes)

    resizer = Kernel.ensure_obj(resizer, max_planes)

    width, height, fmt = model.width, model.height, model.format.replace(subsampling_w=0, subsampling_h=0)

    return ExprOp.MAX.combine(
        split(resizer.scale(clip, width, height, format=fmt)) for clip in clips
    )


def _get_region_expr(
    clip: vs.VideoNode | vs.VideoFrame, left: int = 0, right: int = 0, top: int = 0, bottom: int = 0,
    replace: str | int = 0, rel: bool = False
) -> str:
    right, bottom = right + 1, bottom + 1

    if isinstance(replace, int):
        replace = f'x {replace}'

    if rel:
        return f'X {left} < X {right} > or Y {top} < Y {bottom} > or or {replace} ?'

    return f'X {left} < X {clip.width - right} > or Y {top} < Y {clip.height - bottom} > or or {replace} ?'


def region_rel_mask(clip: vs.VideoNode, left: int = 0, right: int = 0, top: int = 0, bottom: int = 0) -> vs.VideoNode:
    if aka_expr_available:
        return norm_expr(clip, _get_region_expr(clip, left, right, top, bottom, 0), force_akarin=region_rel_mask)

    return clip.std.Crop(left, right, top, bottom).std.AddBorders(left, right, top, bottom)


def region_abs_mask(clip: vs.VideoNode, width: int, height: int, left: int = 0, top: int = 0) -> vs.VideoNode:
    def _crop(w: int, h: int) -> vs.VideoNode:
        return clip.std.CropAbs(width, height, left, top).std.AddBorders(
            left, w - width - left, top, h - height - top
        )

    if 0 in {clip.width, clip.height}:
        if aka_expr_available:
            return norm_expr(
                clip, _get_region_expr(clip, left, left + width, top, top + height, 0, True),
                force_akarin=region_rel_mask
            )

        return clip.std.FrameEval(lambda f, n: _crop(f.width, f.height), clip)

    return region_rel_mask(clip, left, clip.width - width - left, top, clip.height - height - top)


def squaremask(
    clip: vs.VideoNode, width: int, height: int, offset_x: int, offset_y: int, invert: bool = False,
    func: FuncExceptT | None = None
) -> vs.VideoNode:
    """
    Create a square used for simple masking.

    This is a fast and simple mask that's useful for very rough and simple masking.

    :param clip:        The clip to process.
    :param width:       The width of the square. This must be less than clip.width - offset_x.
    :param height:      The height of the square. This must be less than clip.height - offset_y.
    :param offset_x:    The location of the square, offset from the left side of the frame.
    :param offset_y:    The location of the square, offset from the top of the frame.
    :param invert:      Invert the mask. This means everything *but* the defined square will be masked.
                        Default: False.
    :param func:        Function returned for custom error handling.
                        This should only be set by VS package developers.
                        Default: :py:func:`squaremask`.

    :return:            A mask in the shape of a square.
    """
    func = func or squaremask

    assert check_variable(clip, func)

    mask_format = clip.format.replace(color_family=vs.GRAY, subsampling_w=0, subsampling_h=0)

    if offset_x + width > clip.width or offset_y + height > clip.height:
        raise CustomValueError('mask exceeds clip size!')

    if aka_expr_available:
        base_clip = clip.std.BlankClip(None, None, mask_format.id, 1, color=0, keep=True)

        mask = norm_expr(
            base_clip, _get_region_expr(
                clip, offset_x, clip.width - width - offset_x, offset_y, clip.height - height - offset_y,
                'range_max x' if invert else 'x range_max'
            ), force_akarin=func
        )
    else:
        base_clip = clip.std.BlankClip(width, height, mask_format.id, 1, color=get_peak_value(clip), keep=True)

        mask = base_clip.std.AddBorders(
            offset_x, clip.width - width - offset_x, offset_y, clip.height - height - offset_y
        )
        if invert:
            mask = mask.std.Invert()

    if clip.num_frames == 1:
        return mask

    return mask.std.Loop(clip.num_frames)


def replace_squaremask(
    clipa: vs.VideoNode, clipb: vs.VideoNode, mask_params: tuple[int, int, int, int],
    ranges: FrameRangeN | FrameRangesN | None = None, blur_sigma: int | float | None = None,
    invert: bool = False, func: FuncExceptT | None = None, show_mask: bool = False
) -> vs.VideoNode:
    """
    Replace an area of the frame with another clip using a simple square mask.

    This is a convenience wrapper merging square masking and framerange replacing functionalities
    into one function, along with additional utilities such as blurring.

    :param clipa:           Base clip to process.
    :param clipb:           Clip to mask on top of `clipa`.
    :param mask_params:     Parameters passed to `squaremask`. Expects a tuple of (width, height, offset_x, offset_y).
    :param ranges:          Frameranges to replace with the masked clip. If `None`, replaces the entire clip.
                            Default: None.
    :param blur_sigma:      Post-blurring of the mask to help hide hard edges.
                            If you pass an int, a :py:func:`box_blur` will be used.
                            Passing a float will use a :py:func:`gauss_blur` instead.
                            Default: None.
    :param invert:          Invert the mask. This means everything *but* the defined square will be masked.
                            Default: False.
    :param func:            Function returned for custom error handling.
                            This should only be set by VS package developers.
                            Default: :py:func:`squaremask`.
    :param show_mask:       Return the mask instead of the masked clip.

    :return:                Clip with a squaremask applied, and optionally set to specific frameranges.
    """
    func = func or replace_squaremask

    assert check_variable(clipa, func) and check_variable(clipb, func)

    mask = squaremask(clipb[0], *mask_params, invert, func)

    if ranges is None:
        ranges = [(None, None)]

    if isinstance(blur_sigma, int):
        mask = box_blur(mask, blur_sigma)
    elif isinstance(blur_sigma, float):
        mask = gauss_blur(mask, blur_sigma)

    mask = mask.std.Loop(clipa.num_frames)

    if show_mask:
        return mask

    merge = clipa.std.MaskedMerge(clipb, mask)

    return replace_ranges(clipa, merge, ranges)


def freeze_replace_squaremask(
    mask: vs.VideoNode, insert: vs.VideoNode, mask_params: tuple[int, int, int, int],
    frame: int, frame_range: tuple[int, int]
) -> vs.VideoNode:
    start, end = frame_range

    masked_insert = replace_squaremask(mask[frame], insert[frame], mask_params)

    return insert_clip(mask, masked_insert * (end - start + 1), start)


def normalize_mask(
    mask: GenericMaskT, clip: vs.VideoNode, ref: vs.VideoNode | None = None,
    *, ridge: bool = False, **kwargs: Any
) -> vs.VideoNode:
    if isinstance(mask, str):
        mask = EdgeDetect.ensure_obj(mask)

    if isinstance(mask, type):
        mask = mask()

    if isinstance(mask, RidgeDetect) and ridge:
        mask = mask.ridgemask(clip, **kwargs)

    if isinstance(mask, EdgeDetect):
        mask = mask.edgemask(clip, **kwargs)

    if isinstance(mask, GeneralMask):
        mask = mask.get_mask(clip, ref)

    if callable(mask):
        if ref is None:
            raise CustomValueError('This mask function requires a ref to be specified!')

        mask = mask(clip, ref)

    return depth(mask, clip)
