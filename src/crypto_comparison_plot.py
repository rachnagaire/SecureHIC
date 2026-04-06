import matplotlib.pyplot as plt
import pandas as pd
import os
from matplotlib.patches import Patch

# --- Data ---
classical_data = {
    "Algorithm": ["RSA-2048 Encryption", "ECDSA Signature", "SHA-256 Hash"],
    "Type": ["Classical"]*3,
    "Execution Time (ms)": [76.900959, 27.820587, 0.0]
}

postquantum_data = {
    "Algorithm": ["Kyber512", "Kyber768", "Dilithium2", "Dilithium3"],
    "Type": ["Post-Quantum"]*4,
    "Execution Time (ms)": [4.769564, 5.385160, 7.227659, 9.514809]
}

# Combine data
df = pd.concat([pd.DataFrame(classical_data), pd.DataFrame(postquantum_data)], ignore_index=True)

# --- Plot ---
plt.figure(figsize=(10,6))
colors = ["skyblue" if t=="Classical" else "lightcoral" for t in df["Type"]]
bars = plt.bar(df["Algorithm"], df["Execution Time (ms)"], color=colors)

plt.title("Crypto Benchmark: Classical vs Post-Quantum")
plt.ylabel("Execution Time (ms)")
plt.xlabel("Algorithm")

# Annotate bars
for bar in bars:
    yval = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2.0, yval + 1, f'{yval:.2f}', ha='center', va='bottom')

# Legend
legend_elements = [Patch(facecolor='skyblue', label='Classical'),
                   Patch(facecolor='lightcoral', label='Post-Quantum')]
plt.legend(handles=legend_elements)

plt.tight_layout()

# Save plot
output_file = os.path.join(os.getcwd(), "crypto_classical_vs_postquantum.png")
plt.savefig(output_file, dpi=300)
print(f"Plot saved at: {output_file}")

plt.show()