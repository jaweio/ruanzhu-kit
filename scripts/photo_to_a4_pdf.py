#!/usr/bin/env python3
"""Rectify a photographed paper sheet into a one-page A4 PDF."""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageOps
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _solve_linear(matrix, values):
    """Solve a small dense linear system using Gaussian elimination."""
    size = len(values)
    rows = [list(map(float, row)) + [float(value)]
            for row, value in zip(matrix, values)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise ValueError("四角坐标不能构成有效透视变换")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [item / divisor for item in rows[column]]
        for row in range(size):
            if row == column:
                continue
            factor = rows[row][column]
            if factor:
                rows[row] = [item - factor * base
                             for item, base in zip(rows[row], rows[column])]
    return [rows[index][-1] for index in range(size)]


def _validate_corners(values, width, height):
    points = [(float(values[index]), float(values[index + 1]))
              for index in range(0, 8, 2)]
    if any(x < 0 or y < 0 or x >= width or y >= height for x, y in points):
        raise ValueError(f"角点必须位于图像范围内（{width} × {height}）")

    crosses = []
    for index in range(4):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % 4]
        x3, y3 = points[(index + 2) % 4]
        crosses.append((x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2))
    if any(value <= 0 for value in crosses):
        raise ValueError("角点必须按左上、右上、右下、左下顺序组成凸四边形")
    area = abs(sum(points[index][0] * points[(index + 1) % 4][1]
                   - points[(index + 1) % 4][0] * points[index][1]
                   for index in range(4))) / 2
    if area < 100:
        raise ValueError("角点包围区域过小；请检查坐标是否对应整张纸")
    return points


def _perspective_coefficients(points, out_width, out_height):
    """Return PIL inverse-perspective coefficients for TL, TR, BR, BL points."""
    destination = [(0.0, 0.0), (out_width - 1.0, 0.0),
                   (out_width - 1.0, out_height - 1.0), (0.0, out_height - 1.0)]
    matrix = []
    values = []
    for (x, y), (u, v) in zip(destination, points):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)
    return _solve_linear(matrix, values)


def _whiten_neutral_paper(image):
    """Opt-in gentle whitening for bright, low-chroma paper pixels only."""
    red, green, blue = image.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    chroma = ImageChops.difference(maximum, minimum)
    neutral = Image.eval(chroma, lambda value: 255 if value <= 18 else 0)
    luminance = image.convert("L")
    ramp = Image.eval(luminance,
                      lambda value: max(0, min(255, round((value - 115) * 255 / 35))))
    mask = ImageChops.multiply(neutral, ramp)
    white = Image.new("RGB", image.size, (255, 255, 255))
    return Image.composite(white, image, mask)


def _page_size(points, dpi, orientation):
    top = math.dist(points[0], points[1])
    bottom = math.dist(points[3], points[2])
    left = math.dist(points[0], points[3])
    right = math.dist(points[1], points[2])
    inferred = "landscape" if (top + bottom) > (left + right) else "portrait"
    chosen = inferred if orientation == "auto" else orientation
    width_px = round((297 if chosen == "landscape" else 210) / 25.4 * dpi)
    height_px = round((210 if chosen == "landscape" else 297) / 25.4 * dpi)
    page_size = landscape(A4) if chosen == "landscape" else A4
    return chosen, (width_px, height_px), page_size


def convert_image(input_path, output_path, corners, dpi=300,
                  orientation="auto", whiten_background=False):
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise ValueError(f"找不到输入图片：{input_path}")
    if output_path.resolve() == input_path.resolve():
        raise ValueError("输出 PDF 路径不能覆盖输入图片")
    if dpi < 72 or dpi > 1200:
        raise ValueError("DPI 应在 72 到 1200 之间")

    with Image.open(input_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    points = _validate_corners(corners, image.width, image.height)
    chosen, output_dimensions, page_size = _page_size(points, dpi, orientation)
    coefficients = _perspective_coefficients(points, *output_dimensions)
    rectified = image.transform(output_dimensions, Image.Transform.PERSPECTIVE,
                                tuple(coefficients), Image.Resampling.BICUBIC)
    if whiten_background:
        rectified = _whiten_neutral_paper(rectified)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_path), pagesize=page_size, pageCompression=1)
    pdf.setTitle(f"{input_path.stem} - A4")
    pdf.drawImage(ImageReader(rectified), 0, 0, width=page_size[0],
                  height=page_size[1], preserveAspectRatio=False, mask="auto")
    pdf.showPage()
    pdf.save()
    return chosen, output_dimensions


def main():
    parser = argparse.ArgumentParser(description="将纸面照片透视校正为单页 A4 PDF")
    parser.add_argument("image", help="输入照片路径；角点按 EXIF 旋转后的图像坐标填写")
    parser.add_argument("--output", required=True, help="输出 PDF 路径")
    parser.add_argument("--corners", required=True, nargs=8, type=float,
                        metavar=("TL_X", "TL_Y", "TR_X", "TR_Y",
                                 "BR_X", "BR_Y", "BL_X", "BL_Y"),
                        help="纸张四角，顺序为左上、右上、右下、左下")
    parser.add_argument("--dpi", type=int, default=300, help="输出分辨率，默认 300 DPI")
    parser.add_argument("--orientation", choices=("auto", "portrait", "landscape"),
                        default="auto", help="纸张方向，默认根据角点自动判断")
    parser.add_argument("--whiten-background", action="store_true",
                        help="可选提白中性浅色纸面；可能淡化浅灰内容，默认关闭")
    args = parser.parse_args()

    try:
        orientation, dimensions = convert_image(
            args.image, args.output, args.corners, dpi=args.dpi,
            orientation=args.orientation, whiten_background=args.whiten_background)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    mode = "提白增强" if args.whiten_background else "原色"
    print(f"已生成：{Path(args.output).resolve()}")
    print(f"A4 {orientation}，{dimensions[0]} × {dimensions[1]} px，{args.dpi} DPI；{mode}模式")


if __name__ == "__main__":
    main()
