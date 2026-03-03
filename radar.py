import os
import io
import smtplib
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ==============================================================================
# CONFIGURATION
# ==============================================================================
GAMES_FILE = "games.csv"
GIF_FILE = "keno_radar.gif"
FRAME_DURATION_MS = 250     # Fast: true radar feel
HOLD_LAST_FRAME_MS = 1500   # Pause on the final (most current) frame

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ==============================================================================
# BOARD LAYOUT
# ==============================================================================
BOARD_ROWS = 8
BOARD_COLS = 10

# ==============================================================================
# COLOR SCHEME
# Radar persistence: current = bright cyan, fades through the spectrum
# (frames_ago, background_color, text_color)
# ==============================================================================
def get_cell_style(frames_ago):
    """Returns (bg_color, text_color, edge_color) based on how recently drawn."""
    if frames_ago is None:
        return "#0d0d2b", "#2a2a4a", "#1a1a3e"   # Never hit: dark navy
    elif frames_ago == 0:
        return "#00ffff", "#000000", "#ffffff"    # Current: bright cyan
    elif frames_ago == 1:
        return "#ffffff", "#000000", "#cccccc"    # 1 ago: white
    elif frames_ago == 2:
        return "#ff4444", "#ffffff", "#ff8888"    # 2 ago: red
    elif frames_ago == 3:
        return "#ff6600", "#ffffff", "#ffaa44"    # 3 ago: red-orange
    elif frames_ago <= 5:
        return "#ff8c00", "#000000", "#ffcc44"    # 4-5 ago: orange
    elif frames_ago <= 7:
        return "#ffd700", "#000000", "#ffee88"    # 6-7 ago: yellow
    elif frames_ago <= 10:
        return "#44cc44", "#000000", "#88ff88"    # 8-10 ago: green
    elif frames_ago <= 12:
        return "#0088ff", "#ffffff", "#44aaff"    # 11-12 ago: blue
    else:
        return "#1a3a8a", "#8888cc", "#2244aa"    # 13-14 ago: deep blue


# ==============================================================================
# FRAME GENERATOR
# ==============================================================================
def generate_frame(games_data, frame_idx):
    """
    Generate one frame of the radar animation.
    games_data: list of dicts with 'game_id', 'timestamp', 'numbers' (set of ints)
    frame_idx: which game we are currently showing (0=oldest, 14=newest)
    """
    fig = plt.figure(figsize=(13, 9))
    fig.patch.set_facecolor("#0a0a1a")

    # Main board axis
    ax = fig.add_axes([0.02, 0.10, 0.72, 0.78])
    ax.set_facecolor("#0a0a1a")
    ax.set_xlim(-0.1, BOARD_COLS + 0.1)
    ax.set_ylim(-0.1, BOARD_ROWS + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")

    # Draw each cell
    for n in range(1, 81):
        row = (n - 1) // BOARD_COLS   # 0 = top row (numbers 1-10)
        col = (n - 1) % BOARD_COLS

        # Find how recently this number appeared up to current frame
        frames_ago = None
        for ago in range(frame_idx + 1):
            game_idx = frame_idx - ago
            if n in games_data[game_idx]["numbers"]:
                frames_ago = ago
                break

        bg, text_col, edge = get_cell_style(frames_ago)

        # Draw cell (top row = row 0, displayed at top of grid)
        display_row = BOARD_ROWS - 1 - row  # Flip so row 0 is at top visually
        cell_x = col
        cell_y = display_row

        rect = patches.FancyBboxPatch(
            (cell_x + 0.06, cell_y + 0.06),
            0.88, 0.88,
            boxstyle="round,pad=0.04",
            facecolor=bg,
            edgecolor=edge,
            linewidth=0.8,
            zorder=2
        )
        ax.add_patch(rect)

        # Add a subtle glow effect for current frame hits
        if frames_ago == 0:
            glow = patches.FancyBboxPatch(
                (cell_x + 0.02, cell_y + 0.02),
                0.96, 0.96,
                boxstyle="round,pad=0.06",
                facecolor="none",
                edgecolor="#00ffff",
                linewidth=2.5,
                alpha=0.6,
                zorder=1
            )
            ax.add_patch(glow)

        # Number label
        fontsize = 9.5 if n >= 10 else 10.5
        fontweight = "bold" if frames_ago is not None and frames_ago <= 3 else "normal"
        ax.text(
            cell_x + 0.5, cell_y + 0.5, str(n),
            ha="center", va="center",
            color=text_col,
            fontsize=fontsize,
            fontweight=fontweight,
            zorder=3
        )

    # Row labels on the left
    for r in range(BOARD_ROWS):
        display_row = BOARD_ROWS - 1 - r
        start_num = r * BOARD_COLS + 1
        end_num = r * BOARD_COLS + BOARD_COLS
        ax.text(
            -0.05, display_row + 0.5,
            f"{start_num}-{end_num}",
            ha="right", va="center",
            color="#444466", fontsize=6.5
        )

    # -----------------------------------------------------------------------
    # Legend axis (right side)
    # -----------------------------------------------------------------------
    ax_legend = fig.add_axes([0.76, 0.10, 0.22, 0.78])
    ax_legend.set_facecolor("#0a0a1a")
    ax_legend.axis("off")

    legend_title = "SIGNAL AGE"
    ax_legend.text(
        0.5, 0.97, legend_title,
        ha="center", va="top",
        color="#aaaacc", fontsize=9, fontweight="bold",
        transform=ax_legend.transAxes
    )

    legend_items = [
        (0,     "#00ffff", "Current draw"),
        (1,     "#ffffff", "1 game ago"),
        (2,     "#ff4444", "2 games ago"),
        (3,     "#ff6600", "3 games ago"),
        ("4-5", "#ff8c00", "4-5 games ago"),
        ("6-7", "#ffd700", "6-7 games ago"),
        ("8-10","#44cc44", "8-10 games ago"),
        ("11-12","#0088ff","11-12 games ago"),
        ("13-14","#1a3a8a","13-14 games ago"),
        (None,  "#0d0d2b", "Not in window"),
    ]

    y_start = 0.90
    for i, (age, color, label) in enumerate(legend_items):
        y = y_start - i * 0.085
        rect = patches.FancyBboxPatch(
            (0.05, y - 0.025), 0.18, 0.055,
            boxstyle="round,pad=0.01",
            facecolor=color,
            edgecolor="#333355",
            linewidth=0.5,
            transform=ax_legend.transAxes
        )
        ax_legend.add_patch(rect)
        ax_legend.text(
            0.30, y + 0.005, label,
            ha="left", va="center",
            color="#ccccdd", fontsize=7.5,
            transform=ax_legend.transAxes
        )

    # -----------------------------------------------------------------------
    # Current game details in legend
    # -----------------------------------------------------------------------
    game = games_data[frame_idx]
    current_nums = sorted(game["numbers"])
    nums_str = "  ".join(str(n) for n in current_nums)

    y_nums = 0.035
    ax_legend.text(
        0.5, y_nums + 0.04, "CURRENT DRAW:",
        ha="center", va="bottom",
        color="#00ffff", fontsize=7, fontweight="bold",
        transform=ax_legend.transAxes
    )
    # Split into two lines if needed
    nums_line1 = "  ".join(str(n) for n in current_nums[:10])
    nums_line2 = "  ".join(str(n) for n in current_nums[10:])
    ax_legend.text(
        0.5, y_nums,
        nums_line1,
        ha="center", va="top",
        color="#ffffff", fontsize=6.5,
        transform=ax_legend.transAxes,
        fontfamily="monospace"
    )
    if nums_line2:
        ax_legend.text(
            0.5, y_nums - 0.04,
            nums_line2,
            ha="center", va="top",
            color="#ffffff", fontsize=6.5,
            transform=ax_legend.transAxes,
            fontfamily="monospace"
        )

    # -----------------------------------------------------------------------
    # Title and frame counter
    # -----------------------------------------------------------------------
    fig.text(
        0.5, 0.975,
        "GVR Green Game  —  Keno Radar",
        ha="center", va="top",
        color="white", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.5, 0.945,
        f"Game #{game['game_id']}   |   {game['timestamp']}   |   Frame {frame_idx + 1} of {len(games_data)}",
        ha="center", va="top",
        color="#aaaacc", fontsize=9
    )

    # Frame progress bar
    ax_bar = fig.add_axes([0.02, 0.045, 0.72, 0.018])
    ax_bar.set_facecolor("#1a1a2e")
    ax_bar.set_xlim(0, len(games_data))
    ax_bar.set_ylim(0, 1)
    ax_bar.axis("off")

    # Filled portion
    ax_bar.barh(0.5, frame_idx + 1, height=1.0, color="#00ffff", alpha=0.6)
    # Tick marks for each game
    for i in range(len(games_data)):
        ax_bar.axvline(i + 0.5, color="#333355", linewidth=0.5)

    ax_bar.text(
        len(games_data) / 2, 0.5,
        f"← OLDER {'·' * (frame_idx)} ● {'·' * (len(games_data) - frame_idx - 2)} NEWER →",
        ha="center", va="center",
        color="#666688", fontsize=6.5
    )

    # Convert figure to PIL image
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    img = Image.open(buf).copy()
    plt.close(fig)
    buf.close()

    return img.convert("RGB")


# ==============================================================================
# GIF COMPILER
# ==============================================================================
def generate_radar_gif(games_data):
    """Generate the full animated radar GIF from game data."""
    print(f"[Radar] Generating {len(games_data)}-frame radar animation...")
    frames = []

    for i in range(len(games_data)):
        print(f"[Radar] Rendering frame {i + 1} of {len(games_data)}...")
        frame = generate_frame(games_data, i)
        frames.append(frame)

    # Build duration list: normal speed for all frames, hold longer on last
    durations = [FRAME_DURATION_MS] * len(frames)
    durations[-1] = HOLD_LAST_FRAME_MS

    # Save animated GIF
    frames[0].save(
        GIF_FILE,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,  # Loop forever
        optimize=False
    )
    print(f"[Radar] Saved animation to {GIF_FILE}")

    # Also return bytes for email
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False
    )
    buf.seek(0)
    return buf.read()


# ==============================================================================
# EMAIL
# ==============================================================================
def send_radar_email(gif_bytes, games_data):
    """Send the radar GIF as an email attachment."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        print("[Email] Missing credentials. Check GitHub Secrets.")
        return False

    try:
        latest = games_data[-1]
        oldest = games_data[0]

        subject = f"🎯 Keno Radar — Games #{oldest['game_id']} to #{latest['game_id']}"

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#0a0a1a;padding:20px;color:white;">
        <div style="max-width:650px;margin:auto;">
          <div style="background:#1a1a2e;border-radius:8px;padding:24px;text-align:center;
                      border:1px solid #00ffff33;">
            <h1 style="color:#00ffff;margin:0;">🎯 Keno Radar</h1>
            <p style="color:#aaa;margin:8px 0;">GVR Green Game — Last 15 Draws</p>
          </div>

          <div style="background:#111122;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <p style="color:#aaaacc;margin:0 0 8px;">
              <strong style="color:white;">Game Range:</strong>
              #{oldest['game_id']} → #{latest['game_id']}
            </p>
            <p style="color:#aaaacc;margin:0 0 8px;">
              <strong style="color:white;">From:</strong> {oldest['timestamp']}
            </p>
            <p style="color:#aaaacc;margin:0;">
              <strong style="color:white;">To:</strong> {latest['timestamp']}
            </p>
          </div>

          <div style="background:#111122;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <h3 style="color:#00ffff;margin:0 0 10px;">🌈 How to Read the Radar</h3>
            <table style="width:100%;font-size:13px;">
              <tr><td style="color:#00ffff;padding:3px 8px;">■</td><td style="color:#ccc;">Current draw (this frame)</td></tr>
              <tr><td style="color:#ffffff;padding:3px 8px;">■</td><td style="color:#ccc;">1 game ago</td></tr>
              <tr><td style="color:#ff4444;padding:3px 8px;">■</td><td style="color:#ccc;">2-3 games ago</td></tr>
              <tr><td style="color:#ff8c00;padding:3px 8px;">■</td><td style="color:#ccc;">4-5 games ago</td></tr>
              <tr><td style="color:#ffd700;padding:3px 8px;">■</td><td style="color:#ccc;">6-7 games ago</td></tr>
              <tr><td style="color:#44cc44;padding:3px 8px;">■</td><td style="color:#ccc;">8-10 games ago</td></tr>
              <tr><td style="color:#0088ff;padding:3px 8px;">■</td><td style="color:#ccc;">11-14 games ago</td></tr>
            </table>
          </div>

          <p style="color:#555;font-size:11px;margin-top:16px;text-align:center;">
            The animated GIF is attached. Open it in any browser or image viewer to watch the radar loop.<br>
            For analysis purposes only. Past draws do not predict future results.
          </p>
        </div>
        </body></html>
        """

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECIPIENT
        msg.attach(MIMEText(html, "html"))

        # Attach the GIF
        attachment = MIMEBase("image", "gif")
        attachment.set_payload(gif_bytes)
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"keno_radar_{oldest['game_id']}_to_{latest['game_id']}.gif"
        )
        msg.attach(attachment)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

        print(f"[Email] Radar sent to {EMAIL_RECIPIENT}.")
        return True

    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


# ==============================================================================
# MAIN
# ==============================================================================
def run_radar():
    print("\n" + "=" * 60)
    print("[Radar] Starting Keno Radar Generator...")
    print("=" * 60)

    if not os.path.exists(GAMES_FILE):
        print(f"[Radar] {GAMES_FILE} not found. Did the scraper run?")
        return

    df = pd.read_csv(GAMES_FILE)
    df["Game ID"] = df["Game ID"].astype(int)
    df = df.sort_values("Game ID", ascending=True).tail(15).reset_index(drop=True)

    if len(df) < 2:
        print(f"[Radar] Not enough games ({len(df)}). Need at least 2.")
        return

    print(f"[Radar] Loaded {len(df)} games (#{df['Game ID'].iloc[0]} to #{df['Game ID'].iloc[-1]}).")

    # Parse game data into usable format
    games_data = []
    for _, row in df.iterrows():
        parts = str(row["Numbers"]).replace(",", "-").split("-")
        numbers = set()
        for p in parts:
            p = p.strip()
            if p.isdigit() and 1 <= int(p) <= 80:
                numbers.add(int(p))
        games_data.append({
            "game_id": row["Game ID"],
            "timestamp": row["Timestamp"],
            "numbers": numbers,
        })

    gif_bytes = generate_radar_gif(games_data)
    send_radar_email(gif_bytes, games_data)
    print("\n[Radar] Complete.")


if __name__ == "__main__":
    run_radar()
