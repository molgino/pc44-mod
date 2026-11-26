#!/usr/bin/env python3
"""Generate the MPC touchscreen skin and its small state images."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "skins"
W, H = 1280, 628
PAD_W, PAD_H = 48, 50
BG = "#0e1015"
PANEL = "#171a22"
BORDER = "#2a2f3b"
TEXT = "fff4f3ee"
MUTED = "ffadbacb"
BLUE = "ffa7d9ff"  # playhead only
AMBER = "ffffbe70"
STEP_FIELDS = ("Velocity", "Pitch", "Chance", "Gate", "Ratchet", "Chord", "Nudge")
SETTINGS = ("Steps", "Speed", "Direction", "Mode", "Octave", "MIDI Channel",
            "Scale", "Root", "Swing", "Tempo", "Volume")


def dump(name, content):
    (OUT / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")


FONT_FILE = Path(__file__).resolve().parent / "fonts" / "TitilliumWeb-SemiBold.ttf"


def font(size):
    # Button captions are baked into the images: the MPC draws button images
    # above labels, so a label over a button is hidden. Titillium Web matches
    # the font the MPC uses for every other text.
    return ImageFont.truetype(str(FONT_FILE), size)


def rounded(draw, xy, color, outline=None, width=1, radius=8):
    draw.rounded_rectangle(xy, radius, fill=color, outline=outline, width=width)


def assets():
    for page in ("steps", "setup"):
        image = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, W, 78), fill="#141720")
        draw.line((0, 78, W, 78), fill=BORDER)
        rounded(draw, (24, 94, 1009, 500), PANEL, BORDER, radius=15)
        rounded(draw, (24, 514, 1009, 603), PANEL, BORDER, radius=15)
        rounded(draw, (1026, 94, 1255, 603), PANEL, BORDER, radius=15)
        if page == "steps":
            for group in range(4):
                x = 135 + 214 * group
                rounded(draw, (x - 5, 198, x + 201, 484),
                        "#1c202b" if group % 2 == 0 else "#212633", radius=8)
            for y, color in zip((242, 302, 362, 422), ("#ffb86e", "#99cefc", "#d3affb", "#8de2d3")):
                rounded(draw, (39, y, 42, y + 34), color, radius=1)
        else:
            for x, width in ((40, 430), (485, 182), (681, 311)):
                rounded(draw, (x, 181, x + width, 482), "#10131b", BORDER, radius=9)
            for i in range(len(SETTINGS)):
                _, x, y, width = setting_rect(i)
                rounded(draw, (x, y, x + width - 1, y + 68), "#202632", "#303847", radius=7)
        draw.line((1046, 236, 1234, 236), fill=BORDER)
        if page == "setup":
            draw.line((1046, 320, 1234, 320), fill=BORDER)
        image.save(OUT / f"{page}_panel.png")

    # The MPC scales each frame to the step bounds. Keep the source small
    # enough for a 2D texture while using exact per-cell VST value text.
    side, group_size = 24, 129
    strip = Image.new("RGB", (side, side * group_size * 4))
    draw = ImageDraw.Draw(strip)
    for state in range(4):
        fill = ("#222836", "#2b2a2c", "#1f3a50", "#2d5470")[state]
        bar = ("#2c3446", "#c98a45", "#5ea8d8", "#a7d9ff")[state]
        edge = ("#303848", "#6b4f2c", "#a7d9ff", "#a7d9ff")[state]
        for i in range(group_size):
            y = (state * group_size + i) * side
            draw.rectangle((0, y, side - 1, y + side - 1), fill=edge)
            draw.rectangle((1, y + 1, side - 2, y + side - 2), fill=fill)
            height = round((side - 4) * min(i, 127) / 127)
            if state != 0 and height:
                draw.rectangle((2, y + side - 2 - height, side - 3, y + side - 3), fill=bar)
    strip.save(OUT / "cell_strip.png")

    select = Image.new("RGBA", (PAD_W, PAD_H))
    rounded(ImageDraw.Draw(select), (3, 3, PAD_W - 4, PAD_H - 4), None, "#ffffff",
            width=2, radius=5)
    select.save(OUT / "selected.png")
    Image.new("RGBA", (PAD_W, PAD_H)).save(OUT / "transparent.png")
    for prefix, words, width, height in (
        ("slot", ("Follow", "A", "B"), 90, 48),
        ("lane", STEP_FIELDS, 124, 45),
        ("track", ("Track 1", "Track 2", "Track 3", "Track 4"), 95, 42),
    ):
        for i, word in enumerate(words):
            for on in (False, True):
                button_asset(f"{prefix}_{i}_{int(on)}.png", word, width, height, on)
    for i, word in enumerate(MEMORY_BUTTONS):
        button_asset(f"memory_{i}.png", word, 92, 40, False, size=18)
    for name, dims in (("track_setting", (199, 69)), ("tuning_setting", (158, 69)),
                       ("global_setting", (138, 69))):
        off = Image.new("RGBA", dims)
        off.save(OUT / f"{name}_0.png")
        on = off.copy()
        rounded(ImageDraw.Draw(on), (0, 0, dims[0] - 1, dims[1] - 1), None,
                "#ffbe70", width=2, radius=7)
        on.save(OUT / f"{name}_1.png")


MEMORY_BUTTONS = ("Store A", "Store B", "Load to A", "Load to B")


def button_asset(file, word, w, h, on, primary=False, size=20):
    img = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(img)
    fill = "#ffbe70" if primary else ("#443121" if on else "#202632")
    stroke = "#ffbe70" if on else "#303847"
    color = "#18110b" if primary else ("#ffd298" if on else "#e0e7f1")
    rounded(draw, (0, 0, w - 1, h - 1), fill, stroke, width=2 if on else 1, radius=7)
    if word:
        draw.text((w / 2, h / 2), word, font=font(size), fill=color, anchor="mm")
    img.save(OUT / file)


def style(size, colour=TEXT, align="left", weight="Regular"):
    return {"version": 1, "font": {"version": 1, "name": "Titillium Web",
            "style": weight, "height": float(size)}, "colour": colour,
            "justification": f"{align} verticallyCentred", "case": "Original"}


def widget(name, kind, data, xy, handle=None, focus=False):
    mapping = [] if handle is None else [{"key": "Data", "value": f"Parameter {handle}"}]
    return {"version": 2,
            "componentData": {"version": 1, "name": name, "type": kind, "data": data},
            "handle remapping": {"version": 1, "map": mapping},
            "bounds": {"version": 1, "acceptsHWFocus": "Yes" if focus else "No",
                       "showWhenDataModelInvalid": "Show", "whenVisible": "Always",
                       "boundsType": "Absolute", "bounds": " ".join(map(str, xy))}}


def label(name, xy, size, colour=TEXT, param=None, centre=False, bold=False):
    data = {"version": 1, "textStyle": style(size, colour,
            "horizontallyCentred" if centre else "left", "SemiBold" if bold else "Regular"),
            "type": "Text" if param is None else "Value",
            # Fixed text uses the "Data" handle like the SDK's own generator.
            # With "Invalid" the MPC Live III drew no fixed text at all.
            "handleName": "Data"}
    if param is None:
        data["text"] = name
    return widget(name, "Label", data, xy, param)


def button(name, xy, param, on_image, off_image, group=1, ordinal=1, focus=True):
    return widget(name, "Button", {"version": 2, "onImage": on_image, "offImage": off_image,
                  "buttonId": ordinal, "numButtonsInGroup": group, "handleName": "Data",
                  "gestureBehaviour": "Instant"}, xy, param, focus)


def picker(parts, name, words, xy, stride, param):
    x, y, width, height = xy
    for i, word in enumerate(words):
        parts.append(button(word, (x + stride * i, y, width, height), param,
                            f"{name}_{i}_1.png", f"{name}_{i}_0.png", len(words), i))


def common():
    parts = [
        label("PC44", (28, 8, 106, 57), 35, bold=True),
        label("EDITOR", (136, 12, 125, 52), 20, AMBER, bold=True),
        label("USB status", (299, 20, 320, 34), 22, MUTED, param=5),
        label("Pattern", (619, 20, 94, 34), 19, MUTED, bold=True),
        label("View", (40, 98, 170, 36), 23, AMBER, param=12, bold=True),
        label("Grid status", (219, 98, 438, 36), 22, MUTED, param=13),
        label("PLAYBACK", (1046, 109, 187, 29), 16, MUTED, bold=True),
        label("Transport", (1046, 139, 195, 32), 19, param=6, bold=True),
        label("Tempo", (1046, 171, 191, 35), 24, param=8),
        label("PC44 focus", (1046, 206, 190, 25), 17, MUTED, param=11),
        label("PATTERN TUNING", (1046, 251, 190, 25), 16, AMBER, bold=True),
        label("Scale and root", (1046, 279, 190, 36), 21, param=7),
        label("Save on PC44", (1046, 521, 192, 24), 17, MUTED, bold=True),
        label("Shift + 5 saves the", (1046, 549, 192, 22), 17, MUTED),
        label("PC44's selected edit slot", (1046, 570, 195, 22), 17, MUTED),
    ]
    picker(parts, "slot", ("Follow", "A", "B"), (711, 14, 90, 48), 96, 1)
    return parts


def editor(parts, setup=False):
    value, stored, apply = (87, 91, 88) if setup else (3, 89, 4)
    parts += [
        label("Receipt", (40, 547, 288, 34), 17, MUTED, param=10),
        label("STORED", (339, 522, 108, 25), 15, MUTED, bold=True),
        label("Stored value", (339, 551, 138, 35), 23, param=stored, bold=True),
        label("VALUE (LIVE)", (490, 522, 140, 25), 15, AMBER, bold=True),
        label("New value", (640, 520, 205, 28), 22, param=value, bold=True),
        widget("Adjust new value", "Slider",
               {"version": 2, "sliderType": "ColourBar", "direction": "Horizontal",
                "backgroundColour": "ff2a3141", "outlineColour": "ff3b4355",
                "valueColour": "ffcf9459", "isBipolar": False, "handleName": "Data"},
               (489, 558, 500, 26), value, True),
    ]


def steps_page():
    parts = common()
    picker(parts, "lane", STEP_FIELDS, (40, 144, 124, 45), 137, 84)

    def cell_x(step):
        return 135 + step * 51 + step // 4 * 10

    for step in range(16):
        parts.append(label(str(step + 1), (cell_x(step), 207, PAD_W, 23), 17,
                           AMBER if step % 4 == 0 else MUTED, centre=True))
    for row in range(4):
        y = 234 + row * 60
        parts += [label(f"Track {row + 1}", (52, y + 1, 78, 25), 19, bold=True),
                  label(f"Track state {row+1}", (52, y + 26, 82, 21), 16, MUTED, param=16 + row)]
        for step in range(16):
            xy = (cell_x(step), y, PAD_W, PAD_H)
            cell = row * 16 + step
            param = 20 + cell
            parts += [
                widget(f"Step tile {cell + 1}", "Image", {"version": 2, "imageType": "FilmStrip",
                       "colour": "0", "image": "cell_strip.png", "numFrames": 516,
                       "handleName": "Data"}, xy, param),
                label(f"Step value {cell + 1}", xy, 19, param=param, centre=True, bold=True),
                button(f"Select step {cell + 1}", xy, 2, "selected.png", "transparent.png",
                       64, cell, focus=False),
            ]
    parts += [
        label("SELECTED STEP", (1046, 331, 190, 25), 16, MUTED, bold=True),
        label("Step address", (1046, 357, 190, 31), 25, param=2, bold=True),
        label("Pitch and chance", (1046, 397, 190, 25), 21, param=14),
        label("Gate ratchet nudge", (1046, 430, 190, 25), 19, MUTED, param=15),
    ]
    editor(parts)
    return parts


def setting_rect(i):
    if i < 6:
        return "track_setting", 54 + i % 2 * 207, 221 + i // 2 * 80, 199
    if i < 8:
        return "tuning_setting", 497, 221 + (i - 6) * 80, 158
    j = i - 8
    return "global_setting", 694 + j % 2 * 146, 221 + j // 2 * 80, 138


def setup_page():
    parts = common()
    picker(parts, "track", ("Track 1", "Track 2", "Track 3", "Track 4"),
           (580, 135, 95, 42), 101, 86)
    for title, x in (("TRACK SETTINGS", 56), ("PATTERN", 498), ("GLOBAL", 695)):
        parts.append(label(title, (x, 186, 178, 27), 17, AMBER, bold=True))
    for i, title in enumerate(SETTINGS):
        group, x, y, w = setting_rect(i)
        parts += [
            label(title, (x + 12, y + 6, w - 24, 24), 16, MUTED),
            label(f"{title} current", (x + 12, y + 30, w - 24, 30), 22, param=92 + i + (i == 10), bold=True),
            button(f"Select {title}", (x, y, w, 69), 85, f"{group}_1.png", f"{group}_0.png",
                   len(SETTINGS), i, focus=False),
        ]
    # Pattern memory: the stored pattern travels with the MPC project and presets.
    parts += [
        label("PATTERN MEMORY", (1046, 328, 190, 25), 16, AMBER, bold=True),
        label("Memory content", (1046, 353, 192, 28), 19, param=108, bold=True),
        label("Memory status", (1046, 482, 194, 24), 16, MUTED, param=109),
    ]
    for i, word in enumerate(MEMORY_BUTTONS):
        xy = (1046 + i % 2 * 98, 390 + i // 2 * 46, 92, 40)
        parts.append(button(word, xy, 104 + i, f"memory_{i}.png", f"memory_{i}.png", focus=False))
    editor(parts, setup=True)
    return parts


def render():
    info = {"version": 1, "type": "CompleteDescription"}
    tabs, assignments = [], []
    for index, (name, panel, components, control_ids) in enumerate((
        ("STEPS", "steps", steps_page(), (1, 84, 2, 3)),
        ("SETUP", "setup", setup_page(), (1, 85, 86, 87)),
    )):
        backdrop = {"version": 1, "colour": "ff0e1015", "image": f"{panel}_panel.png"}
        root = {"version": 2, "actions": [], "backgroundData":
                {"version": 1, "focussed": backdrop, "unfocussed": backdrop},
                "ignoreMousePresses": False, "disableCoarseDataWheel": True,
                "componentsData": components}
        tabs.append({"version": 1, "tabName": name, "fnKeyIndex": index, "fnKeySubIndex": 0,
                     "componentDefinition": root, "qlinkBoundsData": ["32 90 965 504"]})
        mapped = dict(zip((1, 2, 3, 4), control_ids))
        assignments.append({"Tab": index + 1, "SubTab": 1, "Bank Direction": "Column",
                            "Q-Links": {f"Q-Link {i}": mapped.get(i, -1) for i in range(1, 17)}})
    choices = {1: ["Follow", "A", "B"],
               2: [f"T{cell // 16 + 1} / {cell % 16 + 1}" for cell in range(64)],
               84: STEP_FIELDS, 85: SETTINGS, 86: ["1", "2", "3", "4"]}
    dump("TUI.json", {"pageData": {"version": 1, "componentDefinitions":
          {"version": 2, "importFiles": [], "localComponentDefinitions": []},
          "replacementStrings": [{"key": f"Parameter {index}", "value": values}
                                 for index, values in choices.items()],
          "info": info, "tabs": tabs}})
    dump("Q-Links.json", {"version": 4, "info": info, "Screen Mode Q-Links":
         {"version": 4, "map": assignments}, "Program Mode Q-Links": assignments[0]["Q-Links"]})


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    assets()
    render()
