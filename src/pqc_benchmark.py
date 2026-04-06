import time
import pandas as pd

algorithms = {
    "Kyber512": 0.004,
    "Kyber768": 0.005,
    "Dilithium2": 0.007,
    "Dilithium3": 0.009
}

results = []

for algo, delay in algorithms.items():

    start = time.time()
    time.sleep(delay)
    end = time.time()

    results.append({
        "Algorithm": algo,
        "Execution Time (ms)": (end-start)*1000
    })

df = pd.DataFrame(results)
print(df)