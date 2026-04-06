
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
df = pd.read_csv('data/final_large_scale_medicaid_data.csv')

# Training the model on scaled data
features = ['CLAIM_AMOUNT', 'AGE', 'TENURE', 'NO_OF_FAMILY_MEMBERS', 'INCIDENT_HOUR_OF_THE_DAY']
X, y = df[features], df['CLAIM_STATUS']
model = RandomForestClassifier(n_estimators=100, n_jobs=-1) # Parallel Processing enabled
model.fit(X, y)
# Final Database Hardening
df_secure = df.drop(columns=['SSN', 'ACCT_NUMBER', 'ROUTING_NUMBER', 'EMP_ROUTING_NUMBER', 'EMP_ACCT_NUMBER'])
df_secure.to_csv('data/final_secure_medicaid_bigdata.csv', index=False)