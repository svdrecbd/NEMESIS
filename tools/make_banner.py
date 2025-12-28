from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def make_banner():
    # Config
    WIDTH = 1280
    HEIGHT = 640
    BG_COLOR = "#ffffff"  # Clean white background for GitHub
    TEXT_COLOR = "#000000"
    SUBTEXT_COLOR = "#444444"
    
    # Paths
    root = Path(__file__).parent.parent
    font_path = root / "assets/fonts/Typestar OCR Regular.otf"
    logo_path = root / "assets/images/transparent_logo.png"
    out_path = root / "assets/images/header.png"

    # Setup Canvas
    img = Image.new("RGBA", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Load Assets
    try:
        # Scale logo to reasonable size (e.g., 200px high)
        logo = Image.open(logo_path).convert("RGBA")
        logo_aspect = logo.width / logo.height
        new_h = 250
        new_w = int(new_h * logo_aspect)
        logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"Error loading logo: {e}")
        return

    try:
        font_title = ImageFont.truetype(str(font_path), 120)
        font_sub = ImageFont.truetype(str(font_path), 42)
    except Exception as e:
        print(f"Error loading font: {e}")
        return

    # Layout
    # Center everything vertically
    # Logo top centered
    # Title below logo
    # Subtitle below title
    
    center_x = WIDTH // 2
    
    # Draw Logo
    logo_y = 60
    logo_x = center_x - (new_w // 2)
    img.alpha_composite(logo, (logo_x, logo_y))

    # Draw Title "NEMESIS"
    title_text = "NEMESIS"
    # Get text bounding box
    bbox = draw.textbbox((0, 0), title_text, font=font_title)
    text_w = bbox[2] - bbox[0]
    text_x = center_x - (text_w // 2)
    text_y = logo_y + new_h + 20
    draw.text((text_x, text_y), title_text, font=font_title, fill=TEXT_COLOR)

    # Draw Subtitle
    sub_text = "Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States"
    # Wrap subtitle if too long? 1280 is pretty wide, it might fit.
    # Check width
    s_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    s_w = s_bbox[2] - s_bbox[0]
    
    if s_w > WIDTH - 100:
        # Simple split if needed, but let's assume it fits or scale down
        font_sub = ImageFont.truetype(str(font_path), 32)
        s_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
        s_w = s_bbox[2] - s_bbox[0]

    s_x = center_x - (s_w // 2)
    s_y = text_y + 140
    draw.text((s_x, s_y), sub_text, font=font_sub, fill=SUBTEXT_COLOR)

    # Save
    img.save(out_path)
    print(f"Banner saved to {out_path}")

if __name__ == "__main__":
    make_banner()
