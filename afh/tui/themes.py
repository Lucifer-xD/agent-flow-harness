"""The app's 46 themes as terminal colours. The table comes from web/js/appearance.js, and a test
keeps the two the same: id: (name, accent, dark, (bg, side, panel, panel2, panel3, border, border2,
text, text2, text3, code))."""
from __future__ import annotations

from textual.theme import Theme

PRESETS: dict[str, tuple] = {
    'sunset': ('Sunset', '#ff6a2a', True, ('#0e0d0d', '#121010', '#171515', '#1e1b1a', '#292524', '#2a2625', '#3a3533', '#f2efec', '#b4ada6', '#7e776f', '#0b0a0a')),
    'midnight': ('Midnight', '#7c8cff', True, ('#0b0d14', '#0e1019', '#13161f', '#191d28', '#222735', '#242936', '#343a4b', '#e9ecf5', '#aab0c2', '#737a8e', '#080a10')),
    'forest': ('Forest', '#2fbf71', True, ('#0b110e', '#0e1511', '#121a15', '#17211b', '#1f2c24', '#213026', '#2f4236', '#e6efe9', '#a8b8ad', '#6f8276', '#080d0a')),
    'ocean': ('Ocean', '#22b8cf', True, ('#0a1016', '#0d141b', '#111922', '#16202a', '#1d2a36', '#1f2d3a', '#2d4050', '#e4eef5', '#a4b6c4', '#6b8090', '#070c11')),
    'rose': ('Rose', '#ff3d71', True, ('#120d10', '#160f13', '#1b1318', '#22181e', '#2c2027', '#2d2129', '#3f2f38', '#f3e9ee', '#bdaab4', '#85737c', '#0d090b')),
    'aurora': ('Aurora', '#5eead4', True, ('#0a0f12', '#0c1317', '#10181d', '#152027', '#1c2a32', '#1d2b33', '#2b3e48', '#e5f3f2', '#a2bcbd', '#6a8486', '#070b0d')),
    'nebula': ('Nebula', '#b38cff', True, ('#0e0b14', '#120e19', '#17121f', '#1d1727', '#272033', '#272035', '#382e4a', '#efe9f8', '#b6aac8', '#7e7391', '#0a080f')),
    'ember': ('Ember', '#ff5544', True, ('#110b0a', '#150d0c', '#1a1110', '#221615', '#2d1e1c', '#2e1f1d', '#42302d', '#f6ebe8', '#c0aaa5', '#88736e', '#0c0807')),
    'graphite': ('Graphite', '#b6f35c', True, ('#0d0e0f', '#111213', '#16171a', '#1c1e21', '#25282c', '#26292d', '#363a40', '#ebedef', '#a9adb3', '#73787f', '#0a0a0b')),
    'slate': ('Slate', '#5aa9ff', True, ('#0f1318', '#12171d', '#171d24', '#1d242d', '#262f3a', '#28313c', '#38434f', '#e8edf3', '#a9b4c0', '#717d8a', '#0b0e12')),
    'abyss': ('Abyss', '#46c8ff', True, ('#070a10', '#090d15', '#0d121c', '#121926', '#1a2333', '#1b2434', '#2a3648', '#e4ecf8', '#9fb0c8', '#66778f', '#05070b')),
    'velvet': ('Velvet', '#ff4f8b', True, ('#100a10', '#140c14', '#1a111a', '#211622', '#2c1e2d', '#2d1f2e', '#412e43', '#f6eaf4', '#c1a9bd', '#8a7286', '#0b070b')),
    'copper': ('Copper', '#f2994a', True, ('#100d0a', '#14100c', '#1a1510', '#221b15', '#2d241c', '#2e251d', '#43372b', '#f5ede4', '#c2b19f', '#8b7a68', '#0b0907')),
    'matrix': ('Terminal', '#39e58c', True, ('#060908', '#08100c', '#0b1410', '#0f1b15', '#16261d', '#17271e', '#22382b', '#d9f5e4', '#93b8a2', '#5c8069', '#040705')),
    'mono': ('Mono', '#ffffff', True, ('#0c0c0d', '#101011', '#151517', '#1b1b1e', '#242428', '#252529', '#343438', '#ededf0', '#a9a9b2', '#737380', '#09090a')),
    'paper': ('Paper', '#e85a1a', False, ('#f6f3ef', '#efebe6', '#fffdfb', '#f3efea', '#e9e3dc', '#e4ddd5', '#d3cabf', '#1b1715', '#5a534d', '#8c847c', '#f1ede8')),
    'snow': ('Snow', '#3b6cff', False, ('#f4f6fa', '#eceff5', '#ffffff', '#f1f3f8', '#e6e9f0', '#e1e5ec', '#cdd3dd', '#141821', '#525968', '#8a909c', '#eef1f6')),
    'sand': ('Sand', '#c26a1b', False, ('#f7f2ea', '#efe8dd', '#fffcf7', '#f3ece2', '#e8dfd2', '#e2d8ca', '#d0c3b2', '#211a12', '#5e5446', '#928775', '#f2ebe1')),
    'lilac': ('Lilac', '#7a4dff', False, ('#f6f4fb', '#eeebf6', '#ffffff', '#f2eff9', '#e6e1f1', '#e2ddee', '#cec7e0', '#1a1625', '#575068', '#8c859d', '#efecf6')),
    'dawn': ('Dawn', '#e8436b', False, ('#fbf4f3', '#f4eae9', '#fffbfb', '#f7eeed', '#eddfde', '#e9dad9', '#d8c4c3', '#241517', '#62494c', '#977d80', '#f5ebea')),
    'peach': ('Peach', '#f2643a', False, ('#fdf5f1', '#f7ebe5', '#fffcfa', '#faefe9', '#f1e1d9', '#eedcd3', '#dfc6ba', '#2a1912', '#6b5248', '#9d857a', '#f9eee8')),
    'arctic': ('Arctic', '#0b8fd6', False, ('#f2f7fb', '#e8f0f6', '#ffffff', '#eef4f9', '#e0eaf2', '#dbe6ef', '#c3d3e0', '#0f1b26', '#4a5d6e', '#8193a3', '#ebf2f8')),
    'matcha': ('Matcha', '#4d8a2a', False, ('#f5f7ef', '#ecf0e3', '#fdfef9', '#f1f4ea', '#e5eadb', '#e1e7d5', '#ccd5bd', '#1b2213', '#56604a', '#8a947d', '#eef2e6')),
    'ivory': ('Ivory', '#9b5de5', False, ('#faf8f3', '#f2efe7', '#fffefb', '#f5f2ea', '#ebe7dc', '#e7e2d6', '#d6cfbf', '#1f1c16', '#5b564b', '#8f8a7e', '#f4f1e9')),
    'mint': ('Mint', '#1f9d5f', False, ('#f3f9f5', '#eaf3ed', '#ffffff', '#eff6f1', '#e2ece6', '#dde8e1', '#c7d6cc', '#13201a', '#4f5f56', '#86958c', '#ecf3ee')),
    'catppuccin': ('Catppuccin Mocha', '#cba6f7', True, ('#1e1e2e', '#181825', '#232336', '#2a2a3d', '#313244', '#313244', '#45475a', '#cdd6f4', '#a6adc8', '#7f849c', '#11111b')),
    'dracula': ('Dracula', '#bd93f9', True, ('#282a36', '#21222c', '#2d2f3d', '#343746', '#3c3f52', '#383a4a', '#4a4d63', '#f8f8f2', '#c4c6d4', '#7d84a8', '#1e1f29')),
    'nord': ('Nord', '#88c0d0', True, ('#2e3440', '#292e39', '#333a47', '#3b4252', '#434c5e', '#3b4252', '#4c566a', '#eceff4', '#d8dee9', '#8e98ab', '#272c36')),
    'tokyonight': ('Tokyo Night', '#7aa2f7', True, ('#1a1b26', '#16161e', '#1f2030', '#24283b', '#2c3048', '#292e42', '#3b4261', '#c0caf5', '#a9b1d6', '#737aa2', '#13141c')),
    'gruvbox': ('Gruvbox', '#fe8019', True, ('#282828', '#1d2021', '#2e2c2b', '#32302f', '#3c3836', '#3c3836', '#504945', '#ebdbb2', '#bdae93', '#928374', '#1d2021')),
    'rosepine': ('Rosé Pine', '#ebbcba', True, ('#191724', '#16141f', '#1f1d2e', '#26233a', '#2e2a45', '#26233a', '#403d52', '#e0def4', '#c4c0dc', '#908caa', '#13111c')),
    'solarized': ('Solarized', '#268bd2', True, ('#002b36', '#00252f', '#073642', '#0a3d4a', '#0f4654', '#0d4250', '#1b5664', '#eee8d5', '#b3bdbd', '#6f8789', '#00212b')),
    'githubdark': ('GitHub Dark', '#2f81f7', True, ('#0d1117', '#010409', '#161b22', '#1c2128', '#262c36', '#21262d', '#30363d', '#e6edf3', '#9da7b3', '#6e7681', '#090c10')),
    'onedark': ('One Dark', '#61afef', True, ('#282c34', '#21252b', '#2c313a', '#323842', '#3a404b', '#333842', '#454b57', '#dcdfe4', '#abb2bf', '#7f848e', '#1e2227')),
    'monokai': ('Monokai', '#a6e22e', True, ('#272822', '#1f201b', '#2d2e27', '#34352d', '#3e3f37', '#3a3b33', '#4f5045', '#f8f8f2', '#cfcfc2', '#8f908a', '#1b1c17')),
    'everforest': ('Everforest', '#a7c080', True, ('#2d353b', '#272e33', '#323c41', '#374247', '#404c51', '#3d484d', '#4f5b58', '#d3c6aa', '#b4ab95', '#859289', '#232a2e')),
    'kanagawa': ('Kanagawa', '#7e9cd8', True, ('#1f1f28', '#16161d', '#252530', '#2a2a37', '#363646', '#2a2a37', '#54546d', '#dcd7ba', '#c8c093', '#727169', '#16161d')),
    'synthwave': ('Synthwave', '#ff7edb', True, ('#1e1631', '#191229', '#241b3a', '#2b2145', '#352a54', '#33284f', '#4a3b70', '#f4eefe', '#c6b8e3', '#8e7fb0', '#150f24')),
    'contrast': ('High Contrast', '#ffd400', True, ('#000000', '#000000', '#0a0a0a', '#121212', '#1e1e1e', '#5a5a5a', '#8a8a8a', '#ffffff', '#e6e6e6', '#bdbdbd', '#000000')),
    'latte': ('Catppuccin Latte', '#8839ef', False, ('#eff1f5', '#e6e9ef', '#f7f8fb', '#e9ecf2', '#dfe3ea', '#dce0e8', '#bcc0cc', '#4c4f69', '#5c5f77', '#8c8fa1', '#e6e9ef')),
    'githublight': ('GitHub Light', '#0969da', False, ('#ffffff', '#f6f8fa', '#ffffff', '#f6f8fa', '#eaeef2', '#d0d7de', '#afb8c1', '#1f2328', '#59636e', '#818b98', '#f6f8fa')),
    'solarizedlight': ('Solarized Light', '#268bd2', False, ('#fdf6e3', '#f5efdc', '#fffbef', '#f3ecd7', '#eae2ca', '#e6dec6', '#d3cbb2', '#073642', '#586e75', '#8a9a9a', '#f2ebd5')),
    'rosepinedawn': ('Rosé Pine Dawn', '#d7827e', False, ('#faf4ed', '#f2e9e1', '#fffaf3', '#f4ede8', '#ebe2da', '#e4dcd4', '#cecacd', '#575279', '#797593', '#9893a5', '#f2e9e1')),
    'gruvboxlight': ('Gruvbox Light', '#d65d0e', False, ('#fbf1c7', '#f2e5bc', '#fdf6d8', '#f2e5bc', '#ebdbb2', '#e5d5ad', '#d5c4a1', '#3c3836', '#665c54', '#928374', '#f2e5bc')),
    'nordlight': ('Nord Light', '#5e81ac', False, ('#eceff4', '#e5e9f0', '#f8f9fb', '#e9edf2', '#dfe4ec', '#d8dee9', '#c2cad8', '#2e3440', '#4c566a', '#7b869a', '#e5e9f0')),
    'contrastlight': ('High Contrast Light', '#0047ff', False, ('#ffffff', '#ffffff', '#ffffff', '#f2f2f2', '#e6e6e6', '#6b6b6b', '#3d3d3d', '#000000', '#1a1a1a', '#404040', '#f2f2f2')),
}

FALLBACK = "sunset"
GOOD = {True: "#4ade80", False: "#15803d"}
BAD = {True: "#f87171", False: "#c02626"}
WARN = {True: "#fbbf24", False: "#b45309"}
GRADIENT = ("#f5a623", "#ff6a2a", "#ff3d71")  # the brand: amber, orange, pink


def build(theme_id: str, name: str, accent: str, dark: bool, colors: tuple) -> Theme:
    bg, side, panel, panel2, panel3, border, border2, text, text2, text3, code = colors
    return Theme(
        name=f"afh-{theme_id}", primary=accent, secondary=accent, accent=accent, foreground=text, background=bg, surface=panel, panel=panel2,
        boost=panel3, success=GOOD[dark], error=BAD[dark], warning=WARN[dark], dark=dark,
        variables={
            "afh-side": side, "afh-panel3": panel3, "afh-border": border, "afh-border2": border2, "afh-text2": text2, "afh-text3": text3, "afh-code": code,
            "block-cursor-foreground": bg, "block-cursor-background": accent, "block-cursor-text-style": "none",
            "input-selection-background": f"{accent} 35%", "footer-background": side,
            "scrollbar": border2, "scrollbar-hover": text3, "scrollbar-active": accent, "scrollbar-background": bg, "scrollbar-background-hover": bg, "scrollbar-background-active": bg, "scrollbar-corner-color": bg,
        },
    )


def all_themes() -> list[Theme]:
    return [build(tid, row[0], row[1], row[2], row[3]) for tid, row in PRESETS.items()]


def mix(a: str, b: str, amount: float) -> str:
    x = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    y = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(p + (q - p) * amount):02x}" for p, q in zip(x, y))


def custom_theme(bg: str, text: str, accent: str) -> Theme:
    """The app's custom colours: surfaces derived from the background and text."""
    lum = sum(int(bg[i:i + 2], 16) * w for i, w in ((1, 0.2126), (3, 0.7152), (5, 0.0722))) / 255
    dark = lum <= 0.5
    step = lambda k: mix(bg, text, k)  # noqa: E731
    return build("custom", "Custom", accent, dark, (bg, step(0.02), step(0.04), step(0.07), step(0.12), step(0.13), step(0.2), text, step(0.7), step(0.5), step(0.01)))


def preset_for(ui: dict) -> str:
    """The preset these settings mean, as the app's resolveTheme does. A terminal can't ask the
    system, so "follow system" stays on the chosen preset."""
    preset = ui.get("preset") or FALLBACK
    if preset == "custom":
        return "custom"
    row = PRESETS.get(preset) or PRESETS[FALLBACK]
    want = {"dark": True, "light": False}.get(ui.get("theme"))
    if want is None or row[2] == want:
        return preset if preset in PRESETS else FALLBACK
    favourite = ui.get("darkPreset" if want else "lightPreset")
    if favourite in PRESETS and PRESETS[favourite][2] == want:
        return favourite
    return "sunset" if want else "paper"


def gradient_text(text: str) -> list[tuple[str, str]]:
    """Pieces of (character, colour) running through the brand gradient."""
    out = []
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        t = i / n * 2
        lo = min(1, int(t))
        out.append((ch, mix(GRADIENT[lo], GRADIENT[lo + 1], t - lo)))
    return out
