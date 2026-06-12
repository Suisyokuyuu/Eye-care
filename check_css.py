import re
from pathlib import Path

ROOT = Path("E:/Dev-with-AI/Eye-care")
WEB = ROOT / "eye_care/ui/web"
CSS_FILES = [
    WEB / "assets/styles/tailwind.css",
    WEB / "assets/styles/base.css",
    WEB / "assets/styles/custom.css",
]

REQUIRED_LAYOUT_CLASSES = {
    "fixed",
    "relative",
    "h-screen",
    "flex",
    "flex-col",
    "flex-1",
    "flex-shrink-0",
    "grid",
    "grid-cols-1",
    "lg:grid-cols-[1.1fr_1fr]",
    "min-h-0",
    "overflow-hidden",
    "w-full",
}


def escape_selector_class(class_name: str) -> str:
    escaped = []
    for ch in class_name:
        if ch.isalnum() or ch in ("-", "_"):
            escaped.append(ch)
        elif ch == ",":
            escaped.append(r"\2c ")
        else:
            escaped.append("\\" + ch)
    return "".join(escaped)


css = "\n".join(path.read_text(encoding="utf-8") for path in CSS_FILES if path.exists())
html = (WEB / "index.html").read_text(encoding="utf-8")

html_classes = set()
for m in re.finditer(r'class="([^"]*)"', html):
    for cls in m.group(1).split():
        cls = cls.strip()
        if cls and not cls.startswith("fa") and not cls.startswith("#"):
            html_classes.add(cls)

missing = []
for cls in sorted(html_classes):
    selector = "." + escape_selector_class(cls)
    if selector not in css:
        missing.append(cls)

missing_required = []
for cls in sorted(REQUIRED_LAYOUT_CLASSES):
    selector = "." + escape_selector_class(cls)
    if selector not in css:
        missing_required.append(cls)

print(f"HTML unique classes: {len(html_classes)}")
print(f"Missing ({len(missing)}):")
for cls in missing[:80]:
    print(f"  {cls}")
if len(missing) > 80:
    print(f"  ... and {len(missing) - 80} more")
print(f"Required layout missing ({len(missing_required)}):")
for cls in missing_required:
    print(f"  {cls}")

if missing or missing_required:
    raise SystemExit(1)
