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
FRAME_DURATION_MS = 250
HOLD_LAST_FRAME_MS = 1500

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
# 2-color system: white (current) fading to dark navy (oldest)
# frames_ago=0 is brightest white, fades through 14 steps to near-invisible
# ==============================================================================
def get_cell_style(frames_ago, total_frames=15):
    """
    Returns (bg_color, text_color, edge_color).
    Current hit = bright white, fades linearly to dark navy over total_frames.
    Never-hit cells = darkest navy background.
    """
    if frames_ago is None:
        # Never hit in the current window
        return "#080818", "#1a1a3a", "#0f0f28"

    # Fade factor: 1.0 = fully white (current), 0.0 = fully dark (oldest)
    fade = 1.0 - (frames_ago / total_frames)

    # Interpolate background from dark navy (#080c2a) to white (#ffffff)
    r = int(8   + fade * (255 - 8))
    g = int(12  + fade * (255 - 12))
    b = int(42  + fade * (255 - 42))
    bg = f"#{r:02x}{g:02x}{b:02x}"

    # Text: dark when background is light, light when background is dark
    if fade > 0.55:
        text_col = "#000000"
    elif fade > 0.30:
        text_col = "#334466"
    else:
        text_col = "#4466aa"

    # Edge: slightly lighter than background
    er = min(255, r + 20)
    eg = min(255, g + 20)
    eb = min(255, b + 20)
    edge = f"#{er:02x}{eg:02x}{eb:02x}"

    return bg, text_col, edge


# ==============================================================================
# FRAME GENERATOR
# ==============================================================================
def generate_frame(games_data, frame_idx):
    total_frames = len(games_data)

    fig = plt.figure(figsize=(13, 9))
    fig.patch.set_facecolor("#0a0a1a")

    ax = fig.add_axes([0.02, 0.10, 0.72, 0.78])
    ax.set_facecolor("#0a0a1a")
    ax.set_xlim(-0.1, BOARD_COLS + 0.1)
    ax.set_ylim(-0.1, BOARD_ROWS + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")

    for n in range(1, 81):
        row = (n - 1) // BOARD_COLS
        col = (n - 1) % BOARD_COLS

        frames_ago = None
        for ago in range(frame_idx + 1):
            game_idx = frame_idx - ago
            if n in games_data[game_idx]["numbers"]:
                frames_ago = ago
                break

        bg, text_col, edge = get_cell_style(frames_ago, total_frames)

        display_row = BOARD_ROWS - 1 - row
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

        # Subtle glow on current frame hits
        if frames_ago == 0:
            glow = patches.FancyBboxPatch(
                (cell_x + 0.02, cell_y + 0.02),
                0.96, 0.96,
                boxstyle="round,pad=0.06",
                facecolor="none",
                edgecolor="#ffffff",
                linewidth=2.5,
                alpha=0.5,
                zorder=1
            )
            ax.add_patch(glow)

        fontsize = 9.5 if n >= 10 else 10.5
        fontweight = "bold" if frames_ago == 0 else "normal"
        ax.text(
            cell_x + 0.5, cell_y + 0.5, str(n),
            ha="center", va="center",
            color=text_col,
            fontsize=fontsize,
            fontweight=fontweight,
            zorder=3
        )

    # Row labels
    for r in range(BOARD_ROWS):
        display_row = BOARD_ROWS - 1 - r
        ax.text(
            -0.05, display_row + 0.5,
            f"{r*10+1}-{r*10+10}",
            ha="right", va="center",
            color="#333355", fontsize=6.5
        )

    # -----------------------------------------------------------------------
    # Legend axis
    # -----------------------------------------------------------------------
    ax_legend = fig.add_axes([0.76, 0.10, 0.22, 0.78])
    ax_legend.set_facecolor("#0a0a1a")
    ax_legend.axis("off")

    ax_legend.text(
        0.5, 0.97, "SIGNAL AGE",
        ha="center", va="top",
        color="#aaaacc", fontsize=9, fontweight="bold",
        transform=ax_legend.transAxes
    )

    # Draw a smooth gradient swatch showing the fade
    gradient_steps = 15
    swatch_height = 0.045
    swatch_top = 0.90
    for i in range(gradient_steps):
        fade = 1.0 - (i / gradient_steps)
        r = int(8   + fade * (255 - 8))
        g = int(12  + fade * (255 - 12))
        b = int(42  + fade * (255 - 42))
        color = f"#{r:02x}{g:02x}{b:02x}"
        y = swatch_top - i * swatch_height
        rect = patches.Rectangle(
            (0.05, y - swatch_height), 0.18, swatch_height,
            facecolor=color,
            edgecolor="none",
            transform=ax_legend.transAxes
        )
        ax_legend.add_patch(rect)

        label = "Current" if i == 0 else (f"{i} ago" if i <= 5 else ("" if i < 14 else "Oldest"))
        if label:
            ax_legend.text(
                0.30, y - swatch_height / 2,
                label,
                ha="left", va="center",
                color="#ccccdd", fontsize=7.5,
                transform=ax_legend.transAxes
            )

    # Never hit swatch
    y_never = swatch_top - gradient_steps * swatch_height - 0.03
    rect = patches.Rectangle(
        (0.05, y_never - swatch_height), 0.18, swatch_height,
        facecolor="#080818",
        edgecolor="#1a1a3a",
        transform=ax_legend.transAxes
    )
    ax_legend.add_patch(rect)
    ax_legend.text(
        0.30, y_never - swatch_height / 2,
        "Not drawn",
        ha="left", va="center",
        color="#ccccdd", fontsize=7.5,
        transform=ax_legend.transAxes
    )

    # Current draw numbers
    game = games_data[frame_idx]
    current_nums = sorted(game["numbers"])
    nums_line1 = "  ".join(str(n) for n in current_nums[:10])
    nums_line2 = "  ".join(str(n) for n in current_nums[10:])

    ax_legend.text(
        0.5, 0.08, "CURRENT DRAW:",
        ha="center", va="bottom",
        color="#ffffff", fontsize=7, fontweight="bold",
        transform=ax_legend.transAxes
    )
    ax_legend.text(
        0.5, 0.05, nums_line1,
        ha="center", va="top",
        color="#ccccdd", fontsize=6.5,
        transform=ax_legend.transAxes,
        fontfamily="monospace"
    )
    if nums_line2:
        ax_legend.text(
            0.5, 0.01, nums_line2,
            ha="center", va="top",
            color="#ccccdd", fontsize=6.5,
            transform=ax_legend.transAxes,
            fontfamily="monospace"
        )

    # -----------------------------------------------------------------------
    # Title and frame info
    # -----------------------------------------------------------------------
    fig.text(
        0.5, 0.975,
        "GVR Green Game  —  Keno Radar",
        ha="center", va="top",
        color="white", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.5, 0.945,
        f"Game #{game['game_id']}   |   {game['timestamp']}   |   Frame {frame_idx + 1} of {total_frames}",
        ha="center", va="top",
        color="#aaaacc", fontsize=9
    )

    # Progress bar
    ax_bar = fig.add_axes([0.02, 0.045, 0.72, 0.018])
    ax_bar.set_facecolor("#1a1a2e")
    ax_bar.set_xlim(0, total_frames)
    ax_bar.set_ylim(0, 1)
    ax_bar.axis("off")
    ax_bar.barh(0.5, frame_idx + 1, height=1.0, color="#ffffff", alpha=0.4)
    for i in range(total_frames):
        ax_bar.axvline(i + 0.5, color="#333355", linewidth=0.5)
    ax_bar.text(
        total_frames / 2, 0.5,
        f"← OLDER {'·' * frame_idx} ● {'·' * (total_frames - frame_idx - 2)} NEWER →",
        ha="center", va="center",
        color="#555577", fontsize=6.5
    )

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
    print(f"[Radar] Generating {len(games_data)}-frame radar animation...")
    frames = []

    for i in range(len(games_data)):
        print(f"[Radar] Rendering frame {i + 1} of {len(games_data)}...")
        frame = generate_frame(games_data, i)
        frames.append(frame)

    durations = [FRAME_DURATION_MS] * len(frames)
    durations[-1] = HOLD_LAST_FRAME_MS

    frames[0].save(
        GIF_FILE,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False
    )
    print(f"[Radar] Saved to {GIF_FILE}")

    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF",
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
                      border:1px solid #ffffff33;">
            <h1 style="color:#ffffff;margin:0;">🎯 Keno Radar</h1>
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
            <h3 style="color:#ffffff;margin:0 0 10px;">How to Read the Radar</h3>
            <p style="color:#aaa;font-size:13px;margin:0;">
              Each frame shows one game. <strong style="color:white;">Bright white</strong> = drawn in this game.
              Numbers fade from white to dark navy as they get older.
              <strong style="color:#555577;">Dark navy</strong> = not drawn in the last 15 games.
            </p>
          </div>
          <p style="color:#555;font-size:11px;margin-top:16px;text-align:center;">
            The animated GIF is attached. Open in any browser or image viewer to watch it loop.<br>
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

        attachment = MIMEBase("image", "gif")
        attachment.set_payload(gif_bytes)
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition", "attachment",
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
