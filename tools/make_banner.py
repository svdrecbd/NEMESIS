from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import textwrap

BANNER_SIZE = (1280, 480)
BANNER_BG_COLOR = "#ffffff"
BANNER_TEXT_COLOR = "#000000"
BANNER_LINE_COLOR = "#000000"
LOGO_TARGET_HEIGHT = 350
LOGO_MARGIN_X = 60
TITLE_FONT_PT = 110
SUBTITLE_FONT_PT = 40
SUBTITLE_LINE_SPACING = 12
SEPARATOR_PADDING = 24
SEPARATOR_HEIGHT = 4
TEXT_MARGIN_X = 60

def make_banner():
    # Config
    width, height = BANNER_SIZE
    
    # Paths
    root = Path(__file__).parent.parent
    font_path = root / "assets/fonts/Typestar OCR Regular.otf"
    logo_path = root / "assets/images/transparent_logo.png"
    out_path = root / "assets/images/header_v2.png"

    # Setup Canvas
    img = Image.new("RGBA", (width, height), BANNER_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Load & Scale Logo (Left Side)
    try:
        logo = Image.open(logo_path).convert("RGBA")
        # Target height: 350px
        logo_h = LOGO_TARGET_HEIGHT
        logo_aspect = logo.width / logo.height
        logo_w = int(logo_h * logo_aspect)
        logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        
        logo_x = LOGO_MARGIN_X
        logo_y = (height - logo_h) // 2
        img.alpha_composite(logo, (logo_x, logo_y))
    except Exception as e:
        print(f"Error loading logo: {e}")
        return

    # 2. Text Setup
    try:
        font_title = ImageFont.truetype(str(font_path), TITLE_FONT_PT)
        font_sub = ImageFont.truetype(str(font_path), SUBTITLE_FONT_PT)
    except Exception as e:
        print(f"Error loading font: {e}")
        return

    # Layout Constraints
    text_start_x = logo_x + logo_w + TEXT_MARGIN_X
    max_text_width = width - text_start_x - TEXT_MARGIN_X
    
    title_text = "NEMESIS"
    raw_subtitle = "Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States"
    
    # 3. Dynamic Wrapping for Subtitle
    words = raw_subtitle.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        # Use simple textbbox for single line check
        bbox = draw.textbbox((0, 0), test_line, font=font_sub)
        w = bbox[2] - bbox[0]
        if w <= max_text_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(' '.join(current_line))
    
    wrapped_subtitle = '\n'.join(lines)

    # 4. Measure Heights (Manual Calculation for Robustness)
    # Title
    t_bbox = draw.textbbox((0, 0), title_text, font=font_title, anchor='lt')
    title_h = t_bbox[3] - t_bbox[1]
    title_w = t_bbox[2] - t_bbox[0]
    
    # Subtitle Height
    # We can calculate it by summing line heights if multiline_textbbox fails with anchor
    line_spacing = SUBTITLE_LINE_SPACING
    # Measure one line to get rough height
    l_bbox = draw.textbbox((0, 0), "Tg", font=font_sub, anchor='lt')
    single_line_h = l_bbox[3] - l_bbox[1]
    subtitle_h = (single_line_h * len(lines)) + (line_spacing * (len(lines) - 1))
    
    # Get max width of subtitle
    sub_w = 0
    for line in lines:
        lb = draw.textbbox((0,0), line, font=font_sub)
        lw = lb[2] - lb[0]
        if lw > sub_w: sub_w = lw

    separator_padding = SEPARATOR_PADDING
    separator_h = SEPARATOR_HEIGHT
    
    total_content_h = title_h + separator_padding + separator_h + separator_padding + subtitle_h
    
    # Vertical Center
    start_y = (height - total_content_h) // 2
    
    # 5. Draw
    # Title
    draw.text((text_start_x, start_y), title_text, font=font_title, fill=BANNER_TEXT_COLOR, anchor='lt')
    
    # Separator
    line_y = start_y + title_h + separator_padding
    line_width = max(title_w, sub_w)
    
    draw.line([(text_start_x, line_y), (text_start_x + line_width, line_y)], fill=BANNER_LINE_COLOR, width=separator_h)
    
    # Subtitle
    sub_y = line_y + separator_h + separator_padding
    # Draw line by line to avoid multiline anchor issues
    current_y = sub_y
    for line in lines:
        draw.text((text_start_x, current_y), line, font=font_sub, fill=BANNER_TEXT_COLOR, anchor='lt')
        current_y += single_line_h + line_spacing

    # Save
    img.save(out_path)
    print(f"Banner saved to {out_path}")

if __name__ == "__main__":
    make_banner()
