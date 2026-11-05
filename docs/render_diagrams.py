"""Render the system architecture and user flows into a downloadable PNG."""

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "system-architecture-and-user-flows.png"
WIDTH = 2800
HEIGHT = 3500
SCALE = 2

COLORS = {
    "background": "#F4F8F7",
    "panel": "#FFFFFF",
    "ink": "#17312D",
    "muted": "#536B65",
    "line": "#8AA69E",
    "green": "#0B6B5E",
    "green_light": "#E3F3EF",
    "blue": "#245B8F",
    "blue_light": "#EAF2FA",
    "amber": "#8C6500",
    "amber_light": "#FFF4D6",
    "purple": "#614A86",
    "purple_light": "#F1ECF8",
    "red": "#9B3C3C",
    "red_light": "#FBECEC",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(f"C:/Windows/Fonts/{filename}", size * SCALE)


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    detail: str = "",
    fill: str | None = None,
    title_color: str | None = None,
    title_size: int = 22,
    detail_size: int = 17,
) -> None:
    x1, y1, x2, y2 = (value * SCALE for value in box)
    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=18 * SCALE,
        fill=fill or COLORS["green_light"],
        outline=title_color or COLORS["green"],
        width=2 * SCALE,
    )
    title_font = font(title_size, True)
    detail_font = font(detail_size)
    title_lines = wrap(title, width=max(12, (x2 - x1) // (title_size * SCALE)))
    detail_lines = (
        wrap(detail, width=max(16, (x2 - x1) // (detail_size * SCALE)))
        if detail
        else []
    )
    line_height = (title_size + 7) * SCALE
    detail_height = (detail_size + 6) * SCALE
    text_height = len(title_lines) * line_height + len(detail_lines) * detail_height
    cursor_y = y1 + max(12 * SCALE, ((y2 - y1) - text_height) // 2)
    for line in title_lines:
        width = draw.textbbox((0, 0), line, font=title_font)[2]
        draw.text(
            (x1 + (x2 - x1 - width) // 2, cursor_y),
            line,
            fill=title_color or COLORS["ink"],
            font=title_font,
        )
        cursor_y += line_height
    for line in detail_lines:
        width = draw.textbbox((0, 0), line, font=detail_font)[2]
        draw.text(
            (x1 + (x2 - x1 - width) // 2, cursor_y),
            line,
            fill=COLORS["muted"],
            font=detail_font,
        )
        cursor_y += detail_height


def connector(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    color: str | None = None,
    width: int = 4,
) -> None:
    color = color or COLORS["line"]
    scaled = [(x * SCALE, y * SCALE) for x, y in points]
    draw.line(scaled, fill=color, width=width * SCALE, joint="curve")
    x1, y1 = scaled[-2]
    x2, y2 = scaled[-1]
    direction = 1 if y2 >= y1 else -1
    if abs(x2 - x1) > abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        arrow = [(x2, y2), (x2 - 12 * SCALE * direction, y2 - 7 * SCALE),
                 (x2 - 12 * SCALE * direction, y2 + 7 * SCALE)]
    else:
        arrow = [(x2, y2), (x2 - 7 * SCALE, y2 - 12 * SCALE * direction),
                 (x2 + 7 * SCALE, y2 - 12 * SCALE * direction)]
    draw.polygon(arrow, fill=color)


def section_title(
    draw: ImageDraw.ImageDraw, y: int, number: str, heading: str, subtitle: str
) -> None:
    draw.text(
        (110 * SCALE, y * SCALE),
        number,
        fill=COLORS["green"],
        font=font(22, True),
    )
    draw.text(
        (175 * SCALE, y * SCALE - 3 * SCALE),
        heading,
        fill=COLORS["ink"],
        font=font(31, True),
    )
    draw.text(
        (178 * SCALE, (y + 46) * SCALE),
        subtitle,
        fill=COLORS["muted"],
        font=font(17),
    )


def main() -> None:
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), COLORS["background"])
    draw = ImageDraw.Draw(image)

    draw.text(
        (110 * SCALE, 60 * SCALE),
        "CAR RENTAL MANAGEMENT SYSTEM",
        fill=COLORS["green"],
        font=font(18, True),
    )
    draw.text(
        (110 * SCALE, 100 * SCALE),
        "Architecture & User Flows",
        fill=COLORS["ink"],
        font=font(46, True),
    )
    draw.text(
        (110 * SCALE, 165 * SCALE),
        "Django · MySQL · Gunicorn · Nginx",
        fill=COLORS["muted"],
        font=font(21),
    )

    draw.rounded_rectangle(
        (75 * SCALE, 225 * SCALE, 2725 * SCALE, 1235 * SCALE),
        radius=28 * SCALE,
        fill=COLORS["panel"],
        outline="#D5E4DF",
        width=2 * SCALE,
    )
    section_title(
        draw,
        265,
        "01",
        "System architecture",
        "Production request path and application boundaries",
    )

    rounded_box(
        draw,
        (150, 360, 760, 470),
        "Customer · Staff · Admin",
        "Desktop or mobile browser",
        COLORS["blue_light"],
        COLORS["blue"],
    )
    rounded_box(
        draw,
        (970, 360, 1575, 470),
        "Nginx reverse proxy",
        "TLS termination · forwards HTTPS headers",
        COLORS["blue_light"],
        COLORS["blue"],
    )
    rounded_box(
        draw,
        (1785, 360, 2645, 470),
        "Gunicorn + Django middleware",
        "Security · sessions · CSRF · auth · messages",
        COLORS["green_light"],
        COLORS["green"],
    )
    connector(draw, [(760, 415), (970, 415)])
    connector(draw, [(1575, 415), (1785, 415)])

    app_boxes = [
        ((145, 570, 625, 695), "Accounts", "Email login · roles · profiles", "blue"),
        ((665, 570, 1145, 695), "Vehicles", "Catalog · images · maintenance", "green"),
        ((1185, 570, 1665, 695), "Bookings", "Views · availability API", "amber"),
        ((1705, 570, 2185, 695), "Dashboard", "Operations · reports · CSV", "purple"),
        ((2225, 570, 2655, 695), "Core", "Policies · audit · access control", "red"),
    ]
    for box, title, detail, color in app_boxes:
        rounded_box(
            draw,
            box,
            title,
            detail,
            COLORS[f"{color}_light"],
            COLORS[color],
        )
        connector(
            draw,
            [((box[0] + box[2]) // 2, 470), ((box[0] + box[2]) // 2, box[1])],
            COLORS["line"],
            3,
        )

    rounded_box(
        draw,
        (690, 790, 2110, 900),
        "Booking service layer",
        "Availability overlap + buffer  ·  Pricing quote  ·  Transactional reservation + vehicle lock  ·  Lifecycle",
        COLORS["amber_light"],
        COLORS["amber"],
        title_size=22,
        detail_size=16,
    )
    connector(draw, [(1425, 695), (1425, 790)], COLORS["amber"])

    rounded_box(
        draw,
        (155, 1010, 775, 1140),
        "MySQL 8",
        "Users · fleet · bookings · payments · audit",
        COLORS["blue_light"],
        COLORS["blue"],
    )
    rounded_box(
        draw,
        (870, 1010, 1490, 1140),
        "Persistent media",
        "Uploads · generated WebP thumbnails",
        COLORS["green_light"],
        COLORS["green"],
    )
    rounded_box(
        draw,
        (1585, 1010, 2205, 1140),
        "Email backend",
        "SMTP in production · console in development",
        COLORS["purple_light"],
        COLORS["purple"],
    )
    rounded_box(
        draw,
        (2300, 1010, 2645, 1140),
        "Scheduler",
        "send_reminders",
        COLORS["amber_light"],
        COLORS["amber"],
    )
    connector(draw, [(900, 900), (900, 965), (465, 965), (465, 1010)])
    connector(draw, [(1150, 900), (1150, 1010)])
    connector(draw, [(1650, 900), (1895, 965), (1895, 1010)])
    connector(draw, [(2470, 1010), (2470, 960), (2040, 960), (2040, 900)])
    draw.text(
        (150 * SCALE, 1170 * SCALE),
        "Static assets are collected and served by WhiteNoise; the app reads configuration from environment variables.",
        fill=COLORS["muted"],
        font=font(15),
    )

    draw.rounded_rectangle(
        (75 * SCALE, 1280 * SCALE, 2725 * SCALE, 2350 * SCALE),
        radius=28 * SCALE,
        fill=COLORS["panel"],
        outline="#D5E4DF",
        width=2 * SCALE,
    )
    section_title(
        draw,
        1320,
        "02",
        "Customer journey",
        "Search, validate, book, and manage a rental",
    )

    customer_nodes = [
        ((150, 1475, 700, 1600), "1 · Find a vehicle", "Search dates or browse catalog", "blue"),
        ((1125, 1475, 1675, 1600), "2 · Vehicle details", "Check specs, price, and availability", "blue"),
        ((2100, 1475, 2650, 1600), "3 · Sign in", "Register or log in as a customer", "purple"),
        ((2100, 1770, 2650, 1900), "4 · Profile check", "License valid through return date?", "amber"),
        ((1125, 1770, 1675, 1900), "5 · Request dates", "Choose pickup and return locations", "blue"),
        ((150, 1770, 700, 1900), "6 · Server validation", "Check overlap, maintenance, and buffer", "amber"),
        ((150, 2050, 700, 2180), "7 · Review quote", "Rental · discount · tax · deposit", "green"),
        ((1125, 2050, 1675, 2180), "8 · Atomic booking", "Lock vehicle and recheck availability", "green"),
        ((2100, 2050, 2650, 2180), "9 · Pay and confirm", "Mock card or pay at pickup", "purple"),
    ]
    for box, title, detail, color in customer_nodes:
        rounded_box(
            draw,
            box,
            title,
            detail,
            COLORS[f"{color}_light"],
            COLORS[color],
            title_size=20,
            detail_size=15,
        )

    connector(draw, [(700, 1537), (1125, 1537)])
    connector(draw, [(1675, 1537), (2100, 1537)])
    connector(draw, [(2375, 1600), (2375, 1770)])
    connector(draw, [(2100, 1835), (1675, 1835)])
    connector(draw, [(1125, 1835), (700, 1835)])
    connector(draw, [(425, 1900), (425, 2050)])
    connector(draw, [(700, 2115), (1125, 2115)])
    connector(draw, [(1675, 2115), (2100, 2115)])
    draw.text(
        (2140 * SCALE, 1625 * SCALE),
        "Guest → sign in, then return",
        fill=COLORS["muted"],
        font=font(14),
    )
    draw.text(
        (2145 * SCALE, 1915 * SCALE),
        "If incomplete, update profile",
        fill=COLORS["muted"],
        font=font(14),
    )
    rounded_box(
        draw,
        (1125, 2240, 2650, 2310),
        "After confirmation: booking history · detail · receipt · modify/cancel under policy",
        fill="#F4F8F7",
        title_color=COLORS["muted"],
        title_size=17,
    )
    connector(draw, [(2375, 2180), (2375, 2240)])

    draw.rounded_rectangle(
        (75 * SCALE, 2395 * SCALE, 2725 * SCALE, 3375 * SCALE),
        radius=28 * SCALE,
        fill=COLORS["panel"],
        outline="#D5E4DF",
        width=2 * SCALE,
    )
    section_title(
        draw,
        2435,
        "03",
        "Staff & admin journey",
        "Role gates separate daily operations from administrator-only controls",
    )

    rounded_box(
        draw,
        (150, 2585, 850, 2710),
        "Sign in",
        "Authenticate staff or admin",
        COLORS["blue_light"],
        COLORS["blue"],
    )
    rounded_box(
        draw,
        (1050, 2585, 1750, 2710),
        "Role gate",
        "Staff access · admin access",
        COLORS["amber_light"],
        COLORS["amber"],
    )
    rounded_box(
        draw,
        (1950, 2585, 2650, 2710),
        "Dashboard overview",
        "KPIs · recent rentals · charts",
        COLORS["green_light"],
        COLORS["green"],
    )
    connector(draw, [(850, 2647), (1050, 2647)])
    connector(draw, [(1750, 2647), (1950, 2647)])

    rounded_box(
        draw,
        (160, 2810, 910, 2960),
        "Reservations",
        "Find booking · confirm · pickup · return",
        COLORS["blue_light"],
        COLORS["blue"],
        title_size=20,
        detail_size=15,
    )
    rounded_box(
        draw,
        (1025, 2810, 1775, 2960),
        "Fleet operations",
        "View/status (staff) · CRUD/images (admin)",
        COLORS["green_light"],
        COLORS["green"],
        title_size=20,
        detail_size=15,
    )
    rounded_box(
        draw,
        (1890, 2810, 2640, 2960),
        "Customers",
        "Read/history (staff) · access control (admin)",
        COLORS["purple_light"],
        COLORS["purple"],
        title_size=20,
        detail_size=15,
    )
    for center in (535, 1400, 2265):
        connector(draw, [(2300, 2710), (2300, 2760), (center, 2760), (center, 2810)])

    rounded_box(
        draw,
        (280, 3070, 1120, 3210),
        "Admin-only controls",
        "Staff · maintenance · pricing settings · reports/CSV",
        COLORS["amber_light"],
        COLORS["amber"],
        title_size=20,
        detail_size=15,
    )
    rounded_box(
        draw,
        (1660, 3070, 2500, 3210),
        "Audit history",
        "Track administrative and lifecycle changes",
        COLORS["red_light"],
        COLORS["red"],
        title_size=20,
        detail_size=15,
    )
    connector(draw, [(1400, 2960), (1400, 3020), (700, 3020), (700, 3070)], COLORS["amber"])
    connector(draw, [(700, 3210), (700, 3270), (2080, 3270), (2080, 3210)], COLORS["red"])
    connector(draw, [(535, 2960), (535, 3010), (1870, 3010), (1870, 3070)], COLORS["red"])
    connector(draw, [(1400, 2960), (1400, 3005), (2080, 3005), (2080, 3070)], COLORS["red"])
    draw.text(
        (110 * SCALE, 3425 * SCALE),
        "Car Rental Management System  ·  Architecture overview  ·  See docs/system-architecture.md for details",
        fill=COLORS["muted"],
        font=font(15),
    )

    image.save(OUTPUT, format="PNG", optimize=True, dpi=(180, 180))
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()
