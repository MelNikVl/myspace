"""Генерация фавиконки ShotBox (PNG + ICO) через Pillow."""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = "/home/nik/shotbox/static"
SIZE = 256

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# скруглённый квадрат с градиентом (фиолетово-синий)
grad = Image.new("RGB", (SIZE, SIZE))
gd = ImageDraw.Draw(grad)
for y in range(SIZE):
    for x in range(0, SIZE, 4):
        t = (x + y) / (2 * SIZE)
        r = int(79 + (124 - 79) * t)
        g = int(140 + (92 - 140) * t)
        b = int(255 + (255 - 255) * t)
        gd.rectangle([x, y, x + 4, y + 1], fill=(r, g, b))

mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=56, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)

# корпус камеры
d.rounded_rectangle([54, 88, 202, 190], radius=22, outline=(255, 255, 255), width=13)
# вспышка/кнопка сверху
d.rounded_rectangle([88, 68, 132, 92], radius=8, fill=(255, 255, 255))
# объектив
d.ellipse([103, 111, 153, 161], outline=(255, 255, 255), width=13)
# блик объектива
d.ellipse([118, 126, 132, 140], fill=(255, 255, 255))

img.save(os.path.join(BASE, "favicon.png"), "PNG")
img.resize((64, 64), Image.LANCZOS).save(os.path.join(BASE, "favicon-64.png"), "PNG")
img.resize((48, 48), Image.LANCZOS).save(
    os.path.join(BASE, "favicon.ico"),
    format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
print("готово:", os.path.getsize(os.path.join(BASE, "favicon.png")), "байт PNG,",
      os.path.getsize(os.path.join(BASE, "favicon.ico")), "байт ICO")
