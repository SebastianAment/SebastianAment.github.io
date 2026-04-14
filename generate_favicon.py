#!/usr/bin/env python3
"""Generates a rounded-corner favicon from the profile photo."""

import os
from PIL import Image, ImageDraw

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT = os.path.join(SCRIPT_DIR, "media", "la_square.jpg")
OUTPUT = os.path.join(SCRIPT_DIR, "media", "favicon.png")
SIZE = 180
RADIUS = 30


def generate_favicon(input_path=INPUT, output_path=OUTPUT, size=SIZE, radius=RADIUS):
    img = Image.open(input_path).resize((size, size))
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
    img.putalpha(mask)
    img.save(output_path, "PNG")
    print(f"Saved {output_path} ({size}x{size}, radius={radius})")


if __name__ == "__main__":
    generate_favicon()
