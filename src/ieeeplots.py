import json
import os
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# Paths and data loading
# ============================================================
BASE_DIR = os.path.dirname(__file__)
raw_path = os.path.join(BASE_DIR, "outputs", "benchmark_raw.json")
summary_path = os.path.join(BASE_DIR, "outputs", "benchmark_summary.json")
out_dir = os.path.join(BASE_DIR, "outputs")
os.makedirs(out_dir, exist_ok=True)

with open(raw_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

with open(summary_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# ============================================================
# Plot style
# ============================================================
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "figure.dpi": 300,
    "savefig.dpi": 600,
    "axes.linewidth": 0.8,
})

GRID_KW = {"linestyle": "--", "alpha": 0.35}


# ============================================================
# Helpers
# ============================================================
def add_bar_labels(ax, bars, fmt="{:.2f}", fontsize=7, y_offset_ratio=0.01):
    ymax = max((bar.get_height() for bar in bars), default=0)
    offset = ymax * y_offset_ratio if ymax > 0 else 0.01

    for bar in bars:
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            h + offset,
            fmt.format(h),
            ha="center",
            va="bottom",
            fontsize=fontsize
        )


def add_scatter_overlay(ax, datasets, spread=0.06, marker_size=10):
    for i, values in enumerate(datasets, start=1):
        x = np.full(len(values), i) + np.linspace(-spread, spread, len(values))
        ax.scatter(x, values, s=marker_size, alpha=0.8, color="black", zorder=3)


def filter_stage_data(summary_data, raw_data):
    stage_labels = summary_data.get("stage_labels", [])
    stage_times = summary_data.get("stage_times", [])

    filtered_labels = []
    filtered_times = []

    for label, value in zip(stage_labels, stage_times):
        if label != "Benchmark":
            filtered_labels.append(label)
            filtered_times.append(value)

    heatmap = np.array([
        [row[label] for label in filtered_labels if label in row]
        for row in raw_data.get("stage_breakdown_per_round", [])
    ])

    return filtered_labels, filtered_times, heatmap


# ============================================================
# Stage data without Benchmark
# ============================================================
stage_labels, stage_times, heat = filter_stage_data(data, raw)

# ============================================================
# FIGURE 1: Encryption / Decryption / Storage
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
fig.suptitle("Figure 1. Encryption and Decryption Analysis", fontsize=11)

# (a) Encryption
ax = axes[0, 0]
enc_vals = [data["avg_classical_encrypt"], data["avg_pqc_encrypt"]]
bars = ax.bar(
    ["Classical", "PQC"],
    enc_vals,
    color=["#4C78A8", "#F58518"],
    edgecolor="black"
)
ax.set_title("(a) Encryption")
ax.set_ylabel("Time (s)")
ax.grid(axis="y", **GRID_KW)
add_bar_labels(ax, bars, fmt="{:.2f}")

# (b) Decryption
ax = axes[0, 1]
dec_vals = [data["avg_classical_decrypt"], data["avg_pqc_decrypt"]]
bars = ax.bar(
    ["Classical", "PQC"],
    dec_vals,
    color=["#54A24B", "#E45756"],
    edgecolor="black"
)
ax.set_title("(b) Decryption")
ax.set_ylabel("Time (s)")
ax.grid(axis="y", **GRID_KW)
add_bar_labels(ax, bars, fmt="{:.2f}")

# (c) Crypto box plot
ax = axes[1, 0]
crypto_data = [
    raw["classical_encrypt_times"],
    raw["pqc_encrypt_times"],
    raw["classical_decrypt_times"],
    raw["pqc_decrypt_times"]
]
bp = ax.boxplot(
    crypto_data,
    patch_artist=True,
    showmeans=True,
    widths=0.55
)
crypto_colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756"]
for patch, color in zip(bp["boxes"], crypto_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.8)

for median in bp["medians"]:
    median.set_color("black")
    median.set_linewidth(1.2)

ax.set_xticklabels(["Cls Enc", "PQC Enc", "Cls Dec", "PQC Dec"])
ax.set_title("(c) Crypto Distribution")
ax.set_ylabel("Time (s)")
ax.grid(axis="y", **GRID_KW)
add_scatter_overlay(ax, crypto_data)

# (d) Storage comparison
ax = axes[1, 1]
size_vals = [
    data["original_size_kb"],
    data["classical_size_kb"],
    data["pqc_size_kb"]
]
bars = ax.bar(
    ["Original", "Classical", "PQC"],
    size_vals,
    color=["#72B7B2", "#4C78A8", "#B279A2"],
    edgecolor="black"
)
ax.set_title("(d) Storage Overhead")
ax.set_ylabel("KB")
ax.grid(axis="y", **GRID_KW)
add_bar_labels(ax, bars, fmt="{:.0f}", y_offset_ratio=0.005)

fig.savefig(
    os.path.join(out_dir, "figure1_encryption_decryption_analysis.png"),
    bbox_inches="tight"
)
fig.savefig(
    os.path.join(out_dir, "figure1_encryption_decryption_analysis.pdf"),
    bbox_inches="tight"
)
plt.close(fig)

# ============================================================
# FIGURE 2: Parallel Processing / Scalability
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
fig.suptitle("Figure 2. Parallel Processing Analysis", fontsize=11)

# (a) Sequential vs Parallel
ax = axes[0, 0]
pipe_vals = [data["avg_sequential_pipeline"], data["avg_parallel_pipeline"]]
bars = ax.bar(
    ["Sequential", "Parallel"],
    pipe_vals,
    color=["#54A24B", "#E45756"],
    edgecolor="black"
)
ax.set_title("(a) Execution Mode")
ax.set_ylabel("Time (s)")
ax.grid(axis="y", **GRID_KW)
add_bar_labels(ax, bars, fmt="{:.2f}")

ax.text(
    0.5,
    max(pipe_vals) * 0.90,
    f"Speedup = {data['speedup']:.2f}x",
    ha="center",
    fontsize=7,
    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="black", lw=0.6)
)

# (b) Worker scalability
ax = axes[0, 1]
workers = data["worker_counts"]
times = data["worker_times"]

ax.plot(workers, times, marker="o", linewidth=1.5, color="#4C78A8")
ax.set_title("(b) Worker Scalability")
ax.set_xlabel("Workers")
ax.set_ylabel("Time (s)")
ax.set_xticks(workers)
ax.grid(True, **GRID_KW)

for x, y in zip(workers, times):
    ax.text(x, y, f"{y:.3f}", ha="center", va="bottom", fontsize=7)

# (c) Pipeline box plot
ax = axes[1, 0]
pipe_data = [
    raw["sequential_pipeline_times"],
    raw["parallel_pipeline_times"]
]
bp = ax.boxplot(
    pipe_data,
    patch_artist=True,
    showmeans=True,
    widths=0.55
)
pipe_colors = ["#54A24B", "#E45756"]
for patch, color in zip(bp["boxes"], pipe_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.8)

for median in bp["medians"]:
    median.set_color("black")
    median.set_linewidth(1.2)

ax.set_xticklabels(["Sequential", "Parallel"])
ax.set_title("(c) Pipeline Distribution")
ax.set_ylabel("Time (s)")
ax.grid(axis="y", **GRID_KW)
add_scatter_overlay(ax, pipe_data)

# (d) Stage heatmap
ax = axes[1, 1]
im = ax.imshow(heat, aspect="auto")
ax.set_xticks(range(len(stage_labels)))
ax.set_xticklabels(stage_labels, rotation=20, ha="right")
ax.set_yticks(range(len(heat)))
ax.set_yticklabels([f"R{i+1}" for i in range(len(heat))])
ax.set_title("(d) Stage Heatmap")

for i in range(len(heat)):
    for j in range(len(stage_labels)):
        ax.text(j, i, f"{heat[i, j]:.1f}", ha="center", va="center", fontsize=6)

cbar = fig.colorbar(im, ax=ax)
cbar.set_label("Time (s)")

fig.savefig(
    os.path.join(out_dir, "figure2_parallel_processing_analysis.png"),
    bbox_inches="tight"
)
fig.savefig(
    os.path.join(out_dir, "figure2_parallel_processing_analysis.pdf"),
    bbox_inches="tight"
)
plt.close(fig)

print("Figure 1 and Figure 2 created successfully.")