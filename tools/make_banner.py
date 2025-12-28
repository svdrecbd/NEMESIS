from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def make_banner():
    # Config
    WIDTH = 1280
    HEIGHT = 480 # Slightly shorter for a header feel
    BG_COLOR = "#ffffff"
    TEXT_COLOR = "#000000"
    LINE_COLOR = "#000000"
    
    # Paths
    root = Path(__file__).parent.parent
    font_path = root / "assets/fonts/Typestar OCR Regular.otf"
    logo_path = root / "assets/images/transparent_logo.png"
    out_path = root / "assets/images/header.png"

    # Setup Canvas
    img = Image.new("RGBA", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Load & Scale Logo (Left Side)
    try:
        logo = Image.open(logo_path).convert("RGBA")
        # Target height: 350px with some padding
        logo_h = 350
        logo_aspect = logo.width / logo.height
        logo_w = int(logo_h * logo_aspect)
        logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        
        logo_x = 60
        logo_y = (HEIGHT - logo_h) // 2
        img.alpha_composite(logo, (logo_x, logo_y))
    except Exception as e:
        print(f"Error loading logo: {e}")
        return

    # 2. Text Setup
    try:
        font_title = ImageFont.truetype(str(font_path), 110)
        font_sub = ImageFont.truetype(str(font_path), 44)
    except Exception as e:
        print(f"Error loading font: {e}")
        return

    # Layout Calculations (Right Side)
    text_start_x = logo_x + logo_w + 60
    max_text_width = WIDTH - text_start_x - 60
    
    title_text = "NEMESIS"
    full_subtitle = "Non-periodic Event Monitoring & \nEvaluation of Stimulus-Induced States"
    
    # Calculate Vertical positioning
    # Measure Title
    t_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_h = t_bbox[3] - t_bbox[1]
    
    # Measure Subtitle (multiline)
    line_spacing = 10
    s_bbox = draw.multiline_textbbox((0, 0), full_subtitle, font=font_sub, spacing=line_spacing)
    subtitle_h = s_bbox[3] - s_bbox[1]
    
    separator_padding = 20
    separator_h = 4
    
    total_content_h = title_h + separator_padding + separator_h + separator_padding + subtitle_h
    start_y = (HEIGHT - total_content_h) // 2 - 10 # Slight visual bias up
    
    # 3. Draw Elements
    
    # Title
    draw.text((text_start_x, start_y), title_text, font=font_title, fill=TEXT_COLOR)
    
    # Separator Line
    line_y = start_y + title_h + separator_padding
    # Line width matches the width of the longest subtitle line or title, whichever is wider?
    # Or just fill the remaining space? Let's match the subtitle width for tidiness
    line_width = max(t_bbox[2]-t_bbox[0], s_bbox[2]-s_bbox[0]) + 20
    draw.line([(text_start_x, line_y), (text_start_x + line_width, line_y)], fill=LINE_COLOR, width=separator_h)
    
    # Subtitle
    sub_y = line_y + separator_h + separator_padding
    draw.multiline_text((text_start_x, sub_y), full_subtitle, font=font_sub, fill=TEXT_COLOR, spacing=line_spacing)

    # Save
    img.save(out_path)
    print(f"Banner saved to {out_path}")

if __name__ == "__main__":
    make_banner()