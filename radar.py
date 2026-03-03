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
FRAME_DURATION_MS = 800     # Slower so you can study each intersection
HOLD_LAST_FRAME_MS = 3000   # Hold the final surviving numbers longer

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
# FRAME GENERATOR
# Each frame shows the running intersection of all games seen so far.
# A number stays lit only if it appeared in EVERY game up to this frame.
# New arrivals in the current game flash bright white.
# Survivors from previous frames glow steady cyan.
# Eliminated numbers drop to near-invisible dark navy.
# ==============================================================================
def generate_frame(games_data, frame_idx):
    total_frames = len(games_data)

    # --- Calculate the running intersection ---
    # survivors = numbers that appeared in ALL games from 0 to frame_idx
    survivors = games_data[0]["numbers"].copy()
    for i in range(1, frame_idx + 1):
        survivors = survivors & games_data[i]["numbers"]

    # Numbers in the current game's draw (before intersection filter)
    current_draw = games_data[frame_idx]["numbers"]

    # Numbers that are new candidates this frame (in current draw AND surviving)
    # vs numbers that were already survivors before this frame
    if frame_idx == 0:
        previous_survivors = set()
    else:
        previous_survivors = games_data[0]["numbers"].copy()
        for i in range(1, frame_idx):
            previous_survivors = previous_survivors & games_data[i]["numbers"]

    # Classify each number into a display state
    # "fresh"    = in current draw, is a survivor, wasn't a survivor before
    # "survivor" = was already a survivor and still is
    # "current"  = in current draw but not a survivor (will be eliminated next frame)
    # "dead"     = was in previous survivors but eliminated this frame
    # "cold"     = never appeared in the survivor set

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

        in_current = n in current_draw
        is_survivor = n in survivors
        was_survivor = n in previous_survivors

        if frame_idx == 0:
            # First frame: show all 20 drawn numbers equally bright
            if in_current:
                bg = "#ffffff"
                text_col = "#000000"
                edge = "#ffffff"
                glow_col = "#ffffff"
                do_glow = True
                fontweight = "bold"
            else:
                bg = "#080820"
                text_col = "#1a1a40"
                edge = "#0f0f30"
                do_glow = False
                fontweight = "normal"

        else:
            if is_survivor and was_survivor:
                # Long-term survivor — steady bright cyan
                bg = "#00ddff"
                text_col = "#000000"
                edge = "#00ffff"
                glow_col = "#00ffff"
                do_glow = True
                fontweight = "bold"

            elif is_survivor and not was_survivor:
                # Newly confirmed survivor this frame — flash white
                bg = "#ffffff"
                text_col = "#000000"
                edge = "#ffffff"
                glow_col = "#ffffff"
                do_glow = True
                fontweight = "bold"

            elif in_current and not is_survivor:
                # In current draw but not a survivor — dim white, will die next frame
                bg = "#555566"
                text_col = "#aaaacc"
                edge = "#444455"
                do_glow = False
                fontweight = "normal"

            elif was_survivor and not is_survivor:
                # Just got eliminated — show as faded red briefly
                bg = "#331122"
                text_col = "#553344"
                edge = "#221122"
                do_glow = False
                fontweight = "normal"

            else:
                # Cold — never in the running
                bg = "#080820"
                text_col = "#1a1a40"
                edge = "#0f0f30"
                do_glow = False
                fontweight = "normal"

        rect = patches.FancyBboxPatch(
            (cx + 0.06, cy + 0.06), 0.88, 0.88,
            boxstyle="round,pad=0.04",
            facecolor=bg,
            edgecolor=edge,
            linewidth=0.8,
            zorder=2
        )
        ax.add_patch(rect)

        if do_glow:
            glow = patches.FancyBboxPatch(
                (cx + 0.02, cy + 0.02), 0.96, 0.96,
                boxstyle="round,pad=0.06",
                facecolor="none",
                edgecolor=glow_col,
                linewidth=2.5,
                alpha=0.5,
                zorder=1
            )
            ax.add_patch(glow)

        fontsize = 9.5 if n >= 10 else 10.5
        ax.text(
            cx + 0.5, cy + 0.5, str(n),
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
            color="#222244", fontsize=6.5
        )

    # -----------------------------------------------------------------------
    # Legend
    # -----------------------------------------------------------------------
    ax_leg = fig.add_axes([0.76, 0.10, 0.22, 0.78])
    ax_leg.set_facecolor("#060610")
    ax_leg.axis("off")

    ax_leg.text(
        0.5, 0.97, "LEGEND",
        ha="center", va="top",
        color="#aaaacc", fontsize=9, fontweight="bold",
        transform=ax_leg.transAxes
    )

    legend_items = [
        ("#ffffff", "#000000", "Current draw (frame 1)"),
        ("#00ddff", "#000000", "Surviving (in all games)"),
        ("#555566", "#aaaacc", "In draw, not a survivor"),
        ("#331122", "#553344", "Just eliminated"),
        ("#080820", "#1a1a40",  "Never drawn"),
    ]

    y = 0.88
    for bg, tc, label in legend_items:
        rect = patches.FancyBboxPatch(
            (0.05, y - 0.03), 0.18, 0.055,
            boxstyle="round,pad=0.01",
            facecolor=bg,
            edgecolor="#333355",
            linewidth=0.5,
            transform=ax_leg.transAxes
        )
        ax_leg.add_patch(rect)
        ax_leg.text(
            0.30, y - 0.002, label,
            ha="left", va="center",
            color="#ccccdd", fontsize=7,
            transform=ax_leg.transAxes
        )
        y -= 0.10

    # Survivor count
    survivor_count = len(survivors)
    ax_leg.text(
        0.5, 0.42, f"{survivor_count}",
        ha="center", va="center",
        color="#00ddff" if survivor_count > 0 else "#553344",
        fontsize=36, fontweight="bold",
        transform=ax_leg.transAxes
    )
    ax_leg.text(
        0.5, 0.30,
        "number(s)\nstill alive" if survivor_count > 0 else "no\nsurvivors",
        ha="center", va="center",
        color="#aaaacc", fontsize=8,
        transform=ax_leg.transAxes
    )

    # Surviving numbers list
    if survivors:
        nums_str = "  ".join(str(n) for n in sorted(survivors))
        ax_leg.text(
            0.5, 0.20, nums_str,
            ha="center", va="center",
            color="#00ffff", fontsize=8, fontweight="bold",
            fontfamily="monospace",
            transform=ax_leg.transAxes
        )

    # Current draw numbers
    game = games_data[frame_idx]
    current_nums = sorted(game["numbers"])
    nums_line1 = "  ".join(str(n) for n in current_nums[:10])
    nums_line2 = "  ".join(str(n) for n in current_nums[10:])
    ax_leg.text(
        0.5, 0.11, "THIS DRAW:",
        ha="center", va="bottom",
        color="#888899", fontsize=7, fontweight="bold",
        transform=ax_leg.transAxes
    )
    ax_leg.text(
        0.5, 0.07, nums_line1,
        ha="center", va="top",
        color="#666677", fontsize=6.5, fontfamily="monospace",
        transform=ax_leg.transAxes
    )
    if nums_line2:
        ax_leg.text(
            0.5, 0.03, nums_line2,
            ha="center", va="top",
            color="#666677", fontsize=6.5, fontfamily="monospace",
            transform=ax_leg.transAxes
        )

    # -----------------------------------------------------------------------
    # Title
    # -----------------------------------------------------------------------
    fig.text(
        0.5, 0.975,
        "GVR Green Game  —  Keno Survival Filter",
        ha="center", va="top",
        color="white", fontsize=14, fontweight="bold"
    )
    fig.text(
        0.5, 0.945,
        f"Game #{game['game_id']}   |   {game['timestamp']}   |   Round {frame_idx + 1} of {total_frames}",
        ha="center", va="top",
        color="#aaaacc", fontsize=9
    )

    # Progress bar
    ax_bar = fig.add_axes([0.02, 0.045, 0.72, 0.018])
    ax_bar.set_facecolor("#0f0f28")
    ax_bar.set_xlim(0, total_frames)
    ax_bar.set_ylim(0, 1)
    ax_bar.axis("off")
    ax_bar.barh(0.5, frame_idx + 1, height=1.0,
                color="#00ddff" if survivor_count > 0 else "#553344",
                alpha=0.5)
    for i in range(total_frames):
        ax_bar.axvline(i + 0.5, color="#1a1a3a", linewidth=0.5)
    ax_bar.text(
        total_frames / 2, 0.5,
        f"Game {frame_idx + 1} of {total_frames}  —  {survivor_count} survivor(s)",
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
    print(f"[Radar] Generating {len(games_data)}-frame survival filter animation...")
    frames = []
    for i in range(len(games_data)):
        print(f"[Radar] Rendering frame {i + 1} of {len(games_data)}...")
        frames.append(generate_frame(games_data, i))

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
def send_radar_email(gif_bytes, games_data):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        print("[Email] Missing credentials. Check GitHub Secrets.")
        return False

    try:
        latest = games_data[-1]
        oldest = games_data[0]
        subject = f"🎯 Keno Survival Filter — Games #{oldest['game_id']} to #{latest['game_id']}"

        # Count final survivors
        survivors = games_data[0]["numbers"].copy()
        for g in games_data[1:]:
            survivors = survivors & g["numbers"]
        survivor_list = "  ".join(str(n) for n in sorted(survivors)) if survivors else "None"

        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#060610;padding:20px;color:white;">
        <div style="max-width:650px;margin:auto;">
          <div style="background:#0f0f28;border-radius:8px;padding:24px;text-align:center;
                      border:1px solid #00ddff44;">
            <h1 style="color:#00ddff;margin:0;">🎯 Keno Survival Filter</h1>
            <p style="color:#aaa;margin:8px 0;">GVR Green Game — Last 15 Draws</p>
          </div>

          <div style="background:#0d0d22;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <p style="color:#aaaacc;margin:0 0 8px;">
              <strong style="color:white;">Game Range:</strong>
              #{oldest['game_id']} → #{latest['game_id']}
            </p>
            <p style="color:#aaaacc;margin:0 0 8px;">
              <strong style="color:white;">From:</strong> {oldest['timestamp']}
            </p>
            <p style="color:#aaaacc;margin:0 0 8px;">
              <strong style="color:white;">To:</strong> {latest['timestamp']}
            </p>
            <p style="color:#aaaacc;margin:0;">
              <strong style="color:#00ddff;">Final Survivors:</strong>
              <span style="color:#00ffff;font-family:monospace;font-weight:bold;">
                {survivor_list}
              </span>
            </p>
          </div>

          <div style="background:#0d0d22;border-radius:8px;padding:16px;margin-top:16px;
                      border:1px solid #333355;">
            <h3 style="color:#00ddff;margin:0 0 10px;">How to Read the Filter</h3>
            <p style="color:#aaa;font-size:13px;margin:0 0 8px;">
              <strong style="color:white;">Frame 1:</strong> All 20 numbers from the oldest game light up white.
            </p>
            <p style="color:#aaa;font-size:13px;margin:0 0 8px;">
              <strong style="color:white;">Each frame:</strong> The next game's 20 draws are overlaid.
              Only numbers that appear in <em>both</em> this game and all previous games stay lit.
            </p>
            <p style="color:#aaa;font-size:13px;margin:0;">
              <strong style="color:#00ddff;">Cyan numbers</strong> have survived every game so far.
              Watch the board empty out — the last numbers standing are the ones
              that threaded through all 15 draws.
            </p>
          </div>

          <p style="color:#444;font-size:11px;margin-top:16px;text-align:center;">
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
            filename=f"keno_survival_{oldest['game_id']}_to_{latest['game_id']}.gif"
        )
        msg.attach(attachment)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

        print(f"[Email] Survival filter sent to {EMAIL_RECIPIENT}.")
        return True

    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


# ==============================================================================
# MAIN
# ==============================================================================
def run_radar():
    print("\n" + "=" * 60)
    print("[Radar] Starting Keno Survival Filter...")
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
