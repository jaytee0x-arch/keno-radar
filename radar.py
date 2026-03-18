import os
import io
import smtplib
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.colors as mcolors
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
FRAME_DURATION_MS = 800
HOLD_LAST_FRAME_MS = 4000

# Exponential Decay Constants
# Steady-state heat for a number hit every game = HIT_BOOST / (1 - RETENTION_RATE)
# With these values: 5.0 / (1 - 0.7) = 16.67 — well within MAX_HEAT_DISPLAY
RETENTION_RATE = 0.7    # How much heat carries over each game (70%)
HIT_BOOST = 5.0         # Heat points added when a number is drawn
MAX_HEAT_DISPLAY = 20.0 # Ceiling for color normalization (covers steady-state max)

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

BOARD_ROWS = 8
BOARD_COLS = 10

# Colormap: deep navy → purple → red → yellow → white
HEAT_COLORS = ["#0a0a1a", "#4b0082", "#ff0000", "#ffff00", "#ffffff"]
HEAT_NODES  = [0.0,        0.2,       0.5,       0.8,       1.0     ]
CMAP = mcolors.LinearSegmentedColormap.from_list(
    "keno_heat", list(zip(HEAT_NODES, HEAT_COLORS))
)

# ==============================================================================
# HEAT SIMULATION — Exponential Decay
# Each number starts at a cool baseline.
# Hit = carry over 70% + boost of 5.0
# Miss = carry over 70% only (natural decay toward 0)
# ==============================================================================
def simulate_heat(games_data):
    """Returns a list of heat snapshots, one dict per frame."""
    snapshots = []
    heat = {n: 1.5 for n in range(1, 81)}   # Cool baseline start

    for game in games_data:
        drawn = game["numbers"]
        for n in range(1, 81):
            if n in drawn:
                heat[n] = (heat[n] * RETENTION_RATE) + HIT_BOOST
            else:
                heat[n] = max(0.0, heat[n] * RETENTION_RATE)
        snapshots.append(dict(heat))

    return snapshots


# ==============================================================================
# VISUAL STYLE based on heat intensity
# ==============================================================================
def get_visual(intensity, just_drawn):
    """Returns (bg, text_col, edge, fontsize, fontweight, glow_col, glow_alpha)."""
    if intensity < 0.3:
        return "#060610", "#151535", "#080818", 8.0, "normal", None, 0.0

    norm_val = min(1.0, intensity / MAX_HEAT_DISPLAY)
    bg = mcolors.to_hex(CMAP(norm_val))

    # Text: dark on bright backgrounds, light on dark
    text_col = "#000000" if norm_val > 0.65 else "#ffffff"

    # Edge: white rim on very hot numbers
    edge = "#ffffff" if norm_val > 0.8 else bg

    # Font size scales with heat (8pt cool → 16pt blazing)
    fontsize = 8.0 + (norm_val * 8.0)
    fontweight = "bold" if intensity > 4.0 else "normal"

    # Glow
    if intensity > 8.0:
        glow_col = "#ffff00"
        glow_alpha = 0.6 if just_drawn else 0.3
    elif intensity > 4.0:
        glow_col = "#ff4400"
        glow_alpha = 0.5 if just_drawn else 0.2
    elif just_drawn:
        glow_col = "#ffffff"
        glow_alpha = 0.35
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
    current_heat = snapshots[frame_idx]

    max_h = max(current_heat.values())
    top_5 = sorted(range(1, 81), key=lambda n: current_heat[n], reverse=True)[:5]

    fig = plt.figure(figsize=(13, 9))
    fig.patch.set_facecolor("#060610")

    # Main board
    ax = fig.add_axes([0.02, 0.10, 0.72, 0.78])
    ax.set_facecolor("#060610")
    ax.set_xlim(-0.1, BOARD_COLS + 0.1)
    ax.set_ylim(-0.1, BOARD_ROWS + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")

    for n in range(1, 81):
        row = (n - 1) // BOARD_COLS
        col = (n - 1) % BOARD_COLS
        cx = col
        cy = BOARD_ROWS - 1 - row

        intensity = current_heat[n]
        just_drawn = n in current_draw
        bg, tc, edge, fs, fw, gc, ga = get_visual(intensity, just_drawn)

        rect = patches.FancyBboxPatch(
            (cx + 0.06, cy + 0.06), 0.88, 0.88,
            boxstyle="round,pad=0.04",
            facecolor=bg, edgecolor=edge,
            linewidth=0.8, zorder=2
        )
        ax.add_patch(rect)

        if gc and ga > 0:
            glow = patches.FancyBboxPatch(
                (cx + 0.02, cy + 0.02), 0.96, 0.96,
                boxstyle="round,pad=0.06",
                facecolor="none", edgecolor=gc,
                linewidth=2.5, alpha=ga, zorder=1
            )
            ax.add_patch(glow)

        if intensity > 0.3:
            ax.text(
                cx + 0.5, cy + 0.5, str(n),
                ha="center", va="center",
                color=tc, fontsize=fs, fontweight=fw,
                zorder=3, clip_on=True
            )

    # Row labels
    for r in range(BOARD_ROWS):
        ax.text(
            -0.05, (BOARD_ROWS - 1 - r) + 0.5,
            f"{r*10+1}-{r*10+10}",
            ha="right", va="center",
            color="#1a1a3a", fontsize=6.5
        )

    # -----------------------------------------------------------------------
    # Legend / sidebar
    # -----------------------------------------------------------------------
    ax_leg = fig.add_axes([0.76, 0.10, 0.22, 0.78])
    ax_leg.set_facecolor("#060610")
    ax_leg.set_xlim(0, 1)
    ax_leg.set_ylim(0, 1)
    ax_leg.axis("off")

    ax_leg.text(
        0.5, 0.97, "HEAT INDEX",
        ha="center", va="top",
        color="#aaaacc", fontsize=10, fontweight="bold",
        transform=ax_leg.transAxes
    )

    # Heat scale swatches
    scale_items = [
        ("SUPERNOVA", 18.0),
        ("BLAZING",   12.0),
        ("HOT",        7.0),
        ("WARM",       4.0),
        ("COOL",       1.5),
    ]
    y = 0.88
    for label, val in scale_items:
        bg, _, _, _, _, _, _ = get_visual(val, False)
        rect = patches.FancyBboxPatch(
            (0.05, y - 0.038), 0.20, 0.052,
            boxstyle="round,pad=0.01",
            facecolor=bg, edgecolor="#333355",
            linewidth=0.5,
            transform=ax_leg.transAxes
        )
        ax_leg.add_patch(rect)
        ax_leg.text(
            0.32, y - 0.012, label,
            ha="left", va="center",
            color="#ccccdd", fontsize=7.5,
            transform=ax_leg.transAxes
        )
        y -= 0.088

    # Divider
    ax_leg.plot(
        [0.05, 0.95], [y - 0.01, y - 0.01],
        color="#1a1a3a", linewidth=0.8,
        transform=ax_leg.transAxes
    )

    # Top 5 hottest
    ax_leg.text(
        0.5, y - 0.05, "HOTTEST NUMBERS:",
        ha="center", va="center",
        color="#888899", fontsize=7.5, fontweight="bold",
        transform=ax_leg.transAxes
    )
    for i, n in enumerate(top_5):
        h_pct = min(100, int((current_heat[n] / MAX_HEAT_DISPLAY) * 100))
        col = "#ffff00" if h_pct > 70 else ("#ff4444" if h_pct > 40 else "#8888ff")
        ax_leg.text(
            0.5, y - 0.11 - (i * 0.065),
            f"#{n}  —  {h_pct}%",
            ha="center", va="center",
            color=col, fontsize=8.5,
            fontfamily="monospace",
            transform=ax_leg.transAxes
        )

    # Current draw
    nums = sorted(current_draw)
    line1 = "  ".join(str(n) for n in nums[:10])
    line2 = "  ".join(str(n) for n in nums[10:])
    ax_leg.text(
        0.5, 0.10, "THIS DRAW:",
        ha="center", va="bottom",
        color="#555566", fontsize=7, fontweight="bold",
        transform=ax_leg.transAxes
    )
    ax_leg.text(
        0.5, 0.07, line1,
        ha="center", va="top",
        color="#444455", fontsize=6.5,
        fontfamily="monospace",
        transform=ax_leg.transAxes
    )
    if line2:
        ax_leg.text(
            0.5, 0.03, line2,
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
        "GVR Green Game  —  Keno Heat Radar",
        ha="center", va="top",
        color="white", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.5, 0.945,
        f"Game #{game['game_id']}   |   {game['timestamp']}   |   "
        f"Frame {frame_idx + 1} of {total_frames}   |   Peak: {max_h:.1f}",
        ha="center", va="top",
        color="#aaaacc", fontsize=9
    )

    # Progress bar
    ax_bar = fig.add_axes([0.02, 0.045, 0.72, 0.018])
    ax_bar.set_facecolor("#0f0f28")
    ax_bar.set_xlim(0, total_frames)
    ax_bar.set_ylim(0, 1)
    ax_bar.axis("off")

    bar_color = "#ffff00" if max_h > 8 else ("#ff4400" if max_h > 4 else "#4466ff")
    ax_bar.barh(0.5, frame_idx + 1, height=1.0, color=bar_color, alpha=0.4)
    for i in range(total_frames):
        ax_bar.axvline(i + 0.5, color="#1a1a3a", linewidth=0.5)
    ax_bar.text(
        total_frames / 2, 0.5,
        f"Round {frame_idx + 1} of {total_frames}  —  peak heat {max_h:.1f}",
        ha="center", va="center",
        color="#444466", fontsize=6.5
    )

    # Render to PIL image
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    img = Image.open(buf).copy()   # .copy() detaches from buffer before close
    plt.close(fig)
    buf.close()

    return img.convert("RGB")


# ==============================================================================
# GIF COMPILER
# ==============================================================================
def generate_radar_gif(games_data, snapshots):
    print(f"[Radar] Generating {len(games_data)}-frame heat radar...")
    frames = []
    for i in range(len(games_data)):
        print(f"[Radar] Rendering frame {i + 1} of {len(games_data)}...")
        frames.append(generate_frame(games_data, i, snapshots))

    durations = [FRAME_DURATION_MS] * len(frames)
    durations[-1] = HOLD_LAST_FRAME_MS

    # Save to disk
    frames[0].save(
        GIF_FILE, save_all=True,
        append_images=frames[1:],
        duration=durations, loop=0, optimize=False
    )
    print(f"[Radar] Saved to {GIF_FILE}")

    # Also return as bytes for email (avoids re-reading from disk)
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
        final_heat = snapshots[-1]

        top_10 = sorted(
            range(1, 81),
            key=lambda n: final_heat[n],
            reverse=True
        )[:10]

        rows = ""
        for n in top_10:
            h = final_heat[n]
            h_pct = min(100, int((h / MAX_HEAT_DISPLAY) * 100))
            color = "#ffff00" if h_pct > 70 else ("#ff4444" if h_pct > 40 else "#8888ff")
            bar = "█" * (h_pct // 10) + "░" * (10 - h_pct // 10)
            rows += f"""
            <tr>
              <td style="color:{color};font-weight:bold;padding:5px;font-size:16px;">
                {n}
              </td>
              <td style="color:{color};font-family:monospace;padding:5px;letter-spacing:2px;">
                {bar}
              </td>
              <td style="color:#aaaacc;padding:5px;">
                {h_pct}% intensity
              </td>
            </tr>"""

        subject = f"🔥 Keno Heat Radar — Games #{oldest['game_id']} to #{latest['game_id']}"

        html = f"""
        <html><body style="background:#060610;color:white;font-family:sans-serif;padding:20px;">
        <div style="max-width:620px;margin:auto;border:1px solid #333;
                    padding:24px;border-radius:10px;">
          <h2 style="text-align:center;color:#ffff00;">🔥 Keno Heat Report</h2>
          <p style="text-align:center;color:#aaa;">
            Games #{oldest['game_id']} → #{latest['game_id']}
          </p>
          <p style="text-align:center;color:#666;font-size:13px;">
            {oldest['timestamp']} → {latest['timestamp']}
          </p>
          <h3 style="color:#ffffff;margin-top:20px;">Top 10 Hottest Numbers</h3>
          <table style="width:100%;border-collapse:collapse;">{rows}</table>
          <div style="margin-top:20px;padding:12px;background:#0d0d22;
                      border-radius:6px;font-size:12px;color:#666;">
            <strong style="color:#aaa;">Heat Model:</strong>
            Exponential decay — each game carries {int(RETENTION_RATE*100)}% of previous heat.
            A draw adds +{HIT_BOOST} points. Steady-state max ≈
            {HIT_BOOST / (1 - RETENTION_RATE):.1f} heat units.
          </div>
          <p style="font-size:11px;color:#444;margin-top:16px;text-align:center;">
            Animated GIF attached. Open in any browser or image viewer.<br>
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
            filename=f"keno_heat_{oldest['game_id']}_to_{latest['game_id']}.gif"
        )
        msg.attach(attachment)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

        print(f"[Email] Heat radar sent to {EMAIL_RECIPIENT}.")
        return True

    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


# ==============================================================================
# MAIN
# ==============================================================================
def run_radar():
    print("\n" + "=" * 60)
    print("[Radar] Starting Keno Heat Radar...")
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

    snapshots = simulate_heat(games_data)
    gif_bytes = generate_radar_gif(games_data, snapshots)
    send_radar_email(gif_bytes, games_data, snapshots)

    print("\n[Radar] Complete.")


if __name__ == "__main__":
    run_radar()
