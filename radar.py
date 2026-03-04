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
FRAME_DURATION_MS = 700
HOLD_LAST_FRAME_MS = 3000
STARTING_LIVES = 2      # Each number begins with this many lives
# No max cap — lives accumulate freely each run, reset on next trigger

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
# LIFE SIMULATION
# Runs through all frames and returns a list of dicts, one per frame.
# Each dict maps number -> lives at that point in time.
# ==============================================================================
def simulate_lives(games_data):
    """
    For each frame, compute every number's current life count.
    Rules:
      - All 80 numbers start with STARTING_LIVES
      - Drawn in a game: +1 life
      - Not drawn in a game: -1 life
      - Lives floor at 0 (dead = invisible)
      - No maximum cap
    """
    snapshots = []
    lives = {n: STARTING_LIVES for n in range(1, 81)}

    for game in games_data:
        drawn = game["numbers"]
        for n in range(1, 81):
            if n in drawn:
                lives[n] += 1
            else:
                lives[n] = max(0, lives[n] - 1)
        # Store a copy of the current state
        snapshots.append(dict(lives))

    return snapshots


# ==============================================================================
# VISUAL STYLE based on life count
# 0 lives  = completely dark / invisible
# 1 life   = dim, small
# 2 lives  = medium blue-white
# 3 lives  = bright white
# 4 lives  = bright white + glow
# 5+ lives = blazing white/cyan + strong glow
# ==============================================================================
def get_visual(lives, just_drawn):
    """
    Returns (bg, text_col, edge, fontsize, fontweight, glow_col, glow_alpha)
    just_drawn = True if this number was in the current game's draw
    """
    if lives == 0:
        return "#060610", "#0f0f22", "#080818", 8.0, "normal", None, 0.0

    # Brightness increases with lives
    # Interpolate from dim navy (1 life) to bright white (high lives)
    brightness = min(1.0, (lives - 1) / 5.0)  # Saturates at 6 lives

    r = int(20  + brightness * (255 - 20))
    g = int(30  + brightness * (255 - 30))
    b = int(80  + brightness * (255 - 80))
    bg = f"#{r:02x}{g:02x}{b:02x}"

    # Text color flips from light to dark as background gets bright
    if brightness > 0.6:
        text_col = "#000000"
    elif brightness > 0.3:
        text_col = "#ccddff"
    else:
        text_col = "#7788bb"

    # Edge color
    er = min(255, r + 30)
    eg = min(255, g + 30)
    eb = min(255, b + 20)
    edge = f"#{er:02x}{eg:02x}{eb:02x}"

    # Font size grows with lives
    fontsize = 8.0 + min(lives - 1, 7) * 1.2   # 8pt at 1 life → ~16pt at 8+ lives
    fontweight = "bold" if lives >= 3 else "normal"

    # Glow: only for numbers with 3+ lives, stronger if just drawn
    if lives >= 5:
        glow_col = "#00ffff"
        glow_alpha = 0.8 if just_drawn else 0.5
    elif lives >= 3:
        glow_col = "#ffffff"
        glow_alpha = 0.6 if just_drawn else 0.3
    elif just_drawn:
        glow_col = "#8899ff"
        glow_alpha = 0.3
    else:
        glow_col = None
        glow_alpha = 0.0

    return bg, text_col, edge, fontsize, fontweight, glow_col, glow_alpha


# ==============================================================================
# FRAME GENERATOR
# ==============================================================================
def generate_frame(games_data, frame_idx, snapshots):
    total_frames = len(games_data)
    game = games_data[frame_idx]
    current_draw = game["numbers"]
    current_lives = snapshots[frame_idx]

    # Stats for the legend
    alive = sum(1 for n in range(1, 81) if current_lives[n] > 0)
    max_lives = max(current_lives.values())
    top_numbers = sorted(
        [n for n in range(1, 81) if current_lives[n] > 0],
        key=lambda n: current_lives[n],
        reverse=True
    )[:5]

    fig = plt.figure(figsize=(13, 9))
    fig.patch.set_facecolor("#060610")

    ax = fig.add_axes([0.02, 0.10, 0.72, 0.78])
    ax.set_facecolor("#060610")
    ax.set_xlim(-0.1, BOARD_COLS + 0.1)
    ax.set_ylim(-0.1, BOARD_ROWS + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")

    for n in range(1, 81):
        row = (n - 1) // BOARD_COLS
        col = (n - 1) % BOARD_COLS
        display_row = BOARD_ROWS - 1 - row
        cx = col
        cy = display_row

        lives = current_lives[n]
        just_drawn = n in current_draw

        bg, text_col, edge, fontsize, fontweight, glow_col, glow_alpha = get_visual(lives, just_drawn)

        # Cell background
        rect = patches.FancyBboxPatch(
            (cx + 0.06, cy + 0.06), 0.88, 0.88,
            boxstyle="round,pad=0.04",
            facecolor=bg,
            edgecolor=edge,
            linewidth=0.8,
            zorder=2
        )
        ax.add_patch(rect)

        # Glow ring
        if glow_col and glow_alpha > 0:
            glow = patches.FancyBboxPatch(
                (cx + 0.02, cy + 0.02), 0.96, 0.96,
                boxstyle="round,pad=0.06",
                facecolor="none",
                edgecolor=glow_col,
                linewidth=2.5,
                alpha=glow_alpha,
                zorder=1
            )
            ax.add_patch(glow)

        # Number label — scaled by lives
        if lives > 0:
            ax.text(
                cx + 0.5, cy + 0.5, str(n),
                ha="center", va="center",
                color=text_col,
                fontsize=fontsize,
                fontweight=fontweight,
                zorder=3,
                clip_on=True
            )

    # Row labels
    for r in range(BOARD_ROWS):
        display_row = BOARD_ROWS - 1 - r
        ax.text(
            -0.05, display_row + 0.5,
            f"{r*10+1}-{r*10+10}",
            ha="right", va="center",
            color="#1a1a3a", fontsize=6.5
        )

    # -----------------------------------------------------------------------
    # Legend
    # -----------------------------------------------------------------------
    ax_leg = fig.add_axes([0.76, 0.10, 0.22, 0.78])
    ax_leg.set_facecolor("#060610")
    ax_leg.axis("off")

    ax_leg.text(
        0.5, 0.97, "LIFE SYSTEM",
        ha="center", va="top",
        color="#aaaacc", fontsize=9, fontweight="bold",
        transform=ax_leg.transAxes
    )

    # Visual scale guide
    scale_labels = [
        (1, "1 life  — dim"),
        (2, "2 lives — medium"),
        (3, "3 lives — bright"),
        (5, "5 lives — blazing"),
        (8, "8 lives — champion"),
    ]
    y = 0.89
    for sample_lives, label in scale_labels:
        bg, tc, edge, fs, fw, gc, ga = get_visual(sample_lives, False)
        rect = patches.FancyBboxPatch(
            (0.05, y - 0.032), 0.18, 0.055,
            boxstyle="round,pad=0.01",
            facecolor=bg, edgecolor=edge,
            linewidth=0.5,
            transform=ax_leg.transAxes
        )
        ax_leg.add_patch(rect)
        if gc and ga > 0:
            glow_rect = patches.FancyBboxPatch(
                (0.04, y - 0.038), 0.20, 0.065,
                boxstyle="round,pad=0.01",
                facecolor="none", edgecolor=gc,
                linewidth=1.5, alpha=ga * 0.6,
                transform=ax_leg.transAxes
            )
            ax_leg.add_patch(glow_rect)
        ax_leg.text(
            0.30, y - 0.005, label,
            ha="left", va="center",
            color="#ccccdd", fontsize=7,
            transform=ax_leg.transAxes
        )
        y -= 0.095

    # Separator
    ax_leg.axhline(y - 0.01, xmin=0.05, xmax=0.95,
                   color="#1a1a3a", linewidth=0.8,
                   transform=ax_leg.transAxes)

    # Live stats
    ax_leg.text(
        0.5, y - 0.03,
        f"{alive}  numbers alive",
        ha="center", va="center",
        color="#aaaacc", fontsize=8,
        transform=ax_leg.transAxes
    )
    ax_leg.text(
        0.5, y - 0.08,
        f"Peak: {max_lives} lives",
        ha="center", va="center",
        color="#00ffff" if max_lives >= 5 else "#ffffff",
        fontsize=9, fontweight="bold",
        transform=ax_leg.transAxes
    )

    # Top 5 strongest numbers
    ax_leg.text(
        0.5, y - 0.14,
        "STRONGEST:",
        ha="center", va="center",
        color="#888899", fontsize=7, fontweight="bold",
        transform=ax_leg.transAxes
    )
    for i, n in enumerate(top_numbers):
        lv = current_lives[n]
        _, _, _, fs, fw, gc, _ = get_visual(lv, False)
        col = "#00ffff" if lv >= 5 else "#ffffff"
        ax_leg.text(
            0.5, y - 0.19 - i * 0.055,
            f"{n}  ({'♥' * min(lv, 6)}{'…' if lv > 6 else ''}  {lv} lives)",
            ha="center", va="center",
            color=col, fontsize=7.5,
            fontfamily="monospace",
            transform=ax_leg.transAxes
        )

    # Current draw
    ax_leg.text(
        0.5, 0.09, "THIS DRAW:",
        ha="center", va="bottom",
        color="#555566", fontsize=7, fontweight="bold",
        transform=ax_leg.transAxes
    )
    nums = sorted(current_draw)
    line1 = "  ".join(str(n) for n in nums[:10])
    line2 = "  ".join(str(n) for n in nums[10:])
    ax_leg.text(
        0.5, 0.06, line1,
        ha="center", va="top",
        color="#444455", fontsize=6.5,
        fontfamily="monospace",
        transform=ax_leg.transAxes
    )
    if line2:
        ax_leg.text(
            0.5, 0.02, line2,
            ha="center", va="top",
            color="#444455", fontsize=6.5,
            fontfamily="monospace",
            transform=ax_leg.transAxes
        )

    # -----------------------------------------------------------------------
    # Title and progress bar
    # -----------------------------------------------------------------------
    fig.text(
        0.5, 0.975,
        "GVR Green Game  —  Keno Life System",
        ha="center", va="top",
        color="white", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.5, 0.945,
        f"Game #{game['game_id']}   |   {game['timestamp']}   |   Round {frame_idx + 1} of {total_frames}",
        ha="center", va="top",
        color="#aaaacc", fontsize=9
    )

    ax_bar = fig.add_axes([0.02, 0.045, 0.72, 0.018])
    ax_bar.set_facecolor("#0f0f28")
    ax_bar.set_xlim(0, total_frames)
    ax_bar.set_ylim(0, 1)
    ax_bar.axis("off")
    bar_color = "#00ffff" if max_lives >= 5 else "#4466ff"
    ax_bar.barh(0.5, frame_idx + 1, height=1.0, color=bar_color, alpha=0.4)
    for i in range(total_frames):
        ax_bar.axvline(i + 0.5, color="#1a1a3a", linewidth=0.5)
    ax_bar.text(
        total_frames / 2, 0.5,
        f"Round {frame_idx + 1} of {total_frames}  —  {alive} alive  |  peak {max_lives} lives",
        ha="center", va="center",
        color="#444466", fontsize=6.5
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
    print(f"[Radar] Simulating life system across {len(games_data)} games...")
    snapshots = simulate_lives(games_data)

    print(f"[Radar] Generating {len(games_data)}-frame animation...")
    frames = []
    for i in range(len(games_data)):
        print(f"[Radar] Rendering frame {i + 1} of {len(games_data)}...")
        frames.append(generate_frame(games_data, i, snapshots))

    durations = [FRAME_DURATION_MS] * len(frames)
    durations[-1] = HOLD_LAST_FRAME_MS

    frames[0].save(
        GIF_FILE, save_all=True,
        append_images=frames[1:],
        duration=durations, loop=0, optimize=False
    )
    print(f"[Radar] Saved to {GIF_FILE}")

    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True,
        append_images=frames[1:],
        duration=durations, loop=0, optimize=False
    )
    buf.seek(0)
    return buf.read()


# ==============================================================================
# EMAIL
# ==============================================================================
def send_radar_email(gif_bytes, games_data, snapshots):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        print("[Email] Missing credentials. Check GitHub Secrets.")
        return False

    try:
        latest = games_data[-1]
        oldest = games_data[0]
        final_lives = snapshots[-1]

        # Top survivors by life count
        top_survivors = sorted(
            [(n, final_lives[n]) for n in range(1, 81) if final_lives[n] > 0],
            key=lambda x: x[1], reverse=True
        )[:10]

        survivor_rows = ""
        for n, lv in top_survivors:
            hearts = "♥" * min(lv, 8) + ("…" if lv > 8 else "")
            color = "#00ffff" if lv >= 5 else "#aaaaff"
            survivor_rows += f"""
            <tr>
              <td style="padding:4px 8px;font-size:16px;font-weight:bold;color:{color};">
                {n}
              </td>
              <td style="padding:4px 8px;color:{color};font-family:monospace;">
                {hearts}
              </td>
              <td style="padding:4px 8px;color:#aaaacc;font-size:13px;">
                {lv} lives
              </td>
            </tr>"""

        subject = f"🎯 Keno Life System — Games #{oldest['game_id']} to #{latest['game_id']}"

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#060610;padding:20px;color:white;">
        <div style="max-width:650px;margin:auto;">
          <div style="background:#0f0f28;border-radius:8px;padding:24px;text-align:center;
                      border:1px solid #4466ff44;">
            <h1 style="color:#ffffff;margin:0;">🎯 Keno Life System</h1>
            <p style="color:#aaa;margin:8px 0;">GVR Green Game — Last 15 Draws</p>
          </div>

          <div style="background:#0d0d22;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <p style="color:#aaaacc;margin:0 0 6px;">
              <strong style="color:white;">Game Range:</strong>
              #{oldest['game_id']} → #{latest['game_id']}
            </p>
            <p style="color:#aaaacc;margin:0 0 6px;">
              <strong style="color:white;">From:</strong> {oldest['timestamp']}
            </p>
            <p style="color:#aaaacc;margin:0;">
              <strong style="color:white;">To:</strong> {latest['timestamp']}
            </p>
          </div>

          <div style="background:#0d0d22;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <h3 style="color:#ffffff;margin:0 0 12px;">
              🏆 Final Standings — Top 10 Survivors
            </h3>
            <table style="width:100%;border-collapse:collapse;">
              {survivor_rows}
            </table>
          </div>

          <div style="background:#0d0d22;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <h3 style="color:#ffffff;margin:0 0 10px;">How the Life System Works</h3>
            <p style="color:#aaa;font-size:13px;margin:0 0 6px;">
              Every number starts with <strong style="color:white;">2 lives</strong>.
            </p>
            <p style="color:#aaa;font-size:13px;margin:0 0 6px;">
              <strong style="color:#4488ff;">Drawn this game:</strong> +1 life. Gets bigger and brighter.
            </p>
            <p style="color:#aaa;font-size:13px;margin:0 0 6px;">
              <strong style="color:#ff4444;">Not drawn:</strong> −1 life. Shrinks and dims.
            </p>
            <p style="color:#aaa;font-size:13px;margin:0;">
              <strong style="color:#555566;">0 lives:</strong> Disappears from the board entirely.
              Numbers that reach <strong style="color:#00ffff;">5+ lives</strong> blaze cyan with a glow.
            </p>
          </div>

          <p style="color:#444;font-size:11px;margin-top:16px;text-align:center;">
            Animated GIF attached. Open in any browser or image viewer.<br>
            Life counts reset completely on each new trigger. Fresh start every time.<br>
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
            filename=f"keno_life_{oldest['game_id']}_to_{latest['game_id']}.gif"
        )
        msg.attach(attachment)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

        print(f"[Email] Life system results sent to {EMAIL_RECIPIENT}.")
        return True

    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


# ==============================================================================
# MAIN
# ==============================================================================
def run_radar():
    print("\n" + "=" * 60)
    print("[Radar] Starting Keno Life System...")
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

    print(f"[Radar] Loaded {len(df)} games "
          f"(#{df['Game ID'].iloc[0]} to #{df['Game ID'].iloc[-1]}).")

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

    snapshots = simulate_lives(games_data)
    gif_bytes = generate_radar_gif(games_data)
    send_radar_email(gif_bytes, games_data, snapshots)
    print("\n[Radar] Complete.")


if __name__ == "__main__":
    run_radar()
