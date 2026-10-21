"""Reproduce the NovaDeck vector-style application and tray assets with Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw


def generate(output: Path) -> None:
    size = 256
    image = Image.new('RGBA', (size, size))
    gradient = Image.new('RGBA', (size, size))
    for x in range(size):
        t = x / (size - 1)
        color = tuple(round(a + (b-a)*t) for a, b in zip((124, 92, 255), (34, 211, 238))) + (255,)
        ImageDraw.Draw(gradient).line([(x, 0), (x, size)], fill=color)
    mask = Image.new('L', (size, size))
    drawing = ImageDraw.Draw(mask)
    drawing.rounded_rectangle((4, 4, 252, 252), radius=54, fill=255)
    image.paste(gradient, mask=mask)
    ImageDraw.Draw(image).polygon([(56, 196), (56, 60), (88, 60), (168, 146),
                                  (168, 60), (200, 60), (200, 196), (168, 196), (88, 110), (88, 196)], fill='#0B0F1A')
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / 'novadeck.png')
    image.save(output / 'novadeck.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == '__main__':
    generate(Path(__file__).resolve().parents[1] / 'novadeck' / 'assets')
