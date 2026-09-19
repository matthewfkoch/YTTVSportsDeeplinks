PRODUCT_NAME = "YTTV Sports Deeplinks"
SOURCE_NAME = "yttv-sports"
EYEBROW = "YTTV"
LOGO_PATH = "/static/logo.png"


def for_ui(text: str | None) -> str:
    return (text or "").replace("YouTube TV", "YTTV")
