from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def save_logo_png() -> None:
    size = 1024
    image = Image.new("RGBA", (size, size), "#0b1220")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((64, 64, 960, 960), radius=196, fill="#101827")
    draw.ellipse((198, 198, 826, 826), outline="#38bdf8", width=28)
    draw.arc((250, 250, 774, 774), start=205, end=335, fill="#22c55e", width=38)
    draw.line((512, 256, 512, 768), fill="#e5f2ff", width=34)
    draw.polygon(
        [(512, 208), (590, 485), (512, 445), (434, 485)],
        fill="#f8fafc",
    )
    draw.polygon(
        [(512, 768), (574, 656), (512, 682), (450, 656)],
        fill="#f8fafc",
    )
    draw.line((292, 552, 732, 424), fill="#f8fafc", width=26)
    draw.line((318, 588, 706, 460), fill="#38bdf8", width=10)
    draw.rounded_rectangle((320, 792, 704, 858), radius=33, fill="#22c55e")
    text = "Flights MX"
    text_font = font(48, bold=True)
    bbox = draw.textbbox((0, 0), text, font=text_font)
    draw.text(((size - (bbox[2] - bbox[0])) / 2, 801), text, font=text_font, fill="#062515")

    image.save(ASSETS / "flights-mx-logo.png")


def save_welcome_png() -> None:
    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#0b1220")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        blue = 32 + int(32 * y / height)
        green = 18 + int(24 * y / height)
        draw.line((0, y, width, y), fill=(10, green, blue))

    draw.rounded_rectangle((72, 72, width - 72, height - 72), radius=48, outline="#1f3a5f", width=3)
    draw.ellipse((1050, -180, 1750, 520), outline="#17446b", width=36)
    draw.ellipse((1110, -120, 1690, 460), outline="#1e7a80", width=12)

    logo = Image.open(ASSETS / "flights-mx-logo.png").resize((260, 260))
    image.paste(logo, (110, 116), logo)

    title_font = font(96, bold=True)
    subtitle_font = font(42)
    small_font = font(34)

    draw.text((410, 140), "Flights MX", font=title_font, fill="#f8fafc")
    draw.text((416, 258), "Tu asistente autorizado de vuelos", font=subtitle_font, fill="#b9d7ea")

    lines = [
        "Agrega reservas por PNR, eTicket o URL oficial.",
        "Recibe alertas de cambios operativos.",
        "Check-in solo con tu consentimiento, sin compras ni cambios.",
    ]
    y = 430
    for line in lines:
        draw.rounded_rectangle((156, y - 10, 202, y + 36), radius=10, fill="#22c55e")
        draw.text((228, y - 18), line, font=small_font, fill="#e5f2ff")
        y += 86

    draw.rounded_rectangle((156, 744, 778, 812), radius=34, fill="#38bdf8")
    draw.text((204, 755), "/start  /volaris  /flights", font=font(31, bold=True), fill="#062235")

    image.save(ASSETS / "flights-mx-welcome.png", quality=95)


def save_logo_svg() -> None:
    (ASSETS / "flights-mx-logo.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <rect width="1024" height="1024" rx="196" fill="#101827"/>
  <circle cx="512" cy="512" r="314" fill="none" stroke="#38bdf8" stroke-width="28"/>
  <path d="M265 591a285 285 0 0 0 494-5" fill="none" stroke="#22c55e" stroke-width="38" stroke-linecap="round"/>
  <path d="M512 208l78 277-78-40-78 40 78-277zM512 768l62-112-62 26-62-26 62 112z" fill="#f8fafc"/>
  <path d="M292 552l440-128" stroke="#f8fafc" stroke-width="26" stroke-linecap="round"/>
  <path d="M318 588l388-128" stroke="#38bdf8" stroke-width="10" stroke-linecap="round"/>
</svg>
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    save_logo_png()
    save_welcome_png()
    save_logo_svg()
    print(f"Assets generated in {ASSETS}")
