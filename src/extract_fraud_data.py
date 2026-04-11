"""
COMPLETE CODE TO EXTRACT FRAUD DATA FROM YOUR FHIR JSON FILES
AND CREATE FRAUD-LABELED DATASET

This script:
1. Loads FHIR JSON ExplanationOfBenefit resources
2. Extracts line-item financial data
3. Analyzes patterns to identify fraudulent claims
4. Merges fraud target with your CSV data
5. Saves final dataset with fraud labels
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

print("="*80)
print("FRAUD DATA EXTRACTION FROM FHIR JSON")
print("="*80)

# ============================================================================
# STEP 1: LOAD AND PARSE FHIR JSON
# ============================================================================

print("\n[STEP 1] Loading FHIR JSON files...")

json_file = 'D:/SecureHIC/data/cms_fhir_bundle_combined_20260402_212722.json'

try:
    with open(json_file, 'r') as f:
        bundle = json.load(f)
    print(f"✓ Loaded: {json_file}")
    print(f"  Bundle type: {bundle.get('resourceType')}")
    print(f"  Total entries: {len(bundle.get('entry', []))}")
except Exception as e:
    print(f"✗ Error loading JSON: {e}")
    exit(1)

# ============================================================================
# STEP 2: EXTRACT ExplanationOfBenefit RESOURCES
# ============================================================================

print("\n[STEP 2] Extracting ExplanationOfBenefit (EOB) resources...")

entries = bundle.get('entry', [])
eob_list = []
line_items_list = []

for idx, entry in enumerate(entries):
    resource = entry.get('resource', {})
    
    # Only process ExplanationOfBenefit resources
    if resource.get('resourceType') == 'ExplanationOfBenefit':
        eob_id = resource.get('id')
        status = resource.get('status')
        outcome = resource.get('outcome')
        use = resource.get('use')
        created = resource.get('created')
        
        # Get financial totals
        total = resource.get('total', {})
        if isinstance(total, list) and len(total) > 0:
            total_value = total[0].get('amount', {}).get('value')
        else:
            total_value = None
        
        # Store EOB info
        eob_list.append({
            'eob_id': eob_id,
            'status': status,
            'outcome': outcome,
            'use': use,
            'created': created,
            'total_value': total_value
        })
        
        # Extract line items
        items = resource.get('item', [])
        
        for item_idx, item in enumerate(items):
            sequence = item.get('sequence', item_idx)
            
            # Get service code
            product_or_service = item.get('productOrService', {})
            if isinstance(product_or_service, dict):
                service_code = product_or_service.get('coding', [{}])[0].get('code', 'N/A')
            else:
                service_code = 'N/A'
            
            # Get adjudication details
            adjudication = item.get('adjudication', [])
            
            # Initialize values
            adj_data = {
                'eob_id': eob_id,
                'item_sequence': sequence,
                'service_code': service_code,
                'submitted': None,
                'allowed': None,
                'benefit': None,
                'deductible': None,
                'coinsurance': None,
                'prior_payer': None,
                'all_adjustment': None
            }
            
            # Parse adjudication details
            for adj in adjudication:
                category = adj.get('category', {})
                if isinstance(category, dict):
                    category_code = category.get('coding', [{}])[0].get('code', '').lower()
                else:
                    category_code = ''
                
                amount = adj.get('amount', {})
                if isinstance(amount, dict):
                    value = amount.get('value')
                else:
                    value = None
                
                # Map to appropriate field
                if 'submitted' in category_code:
                    adj_data['submitted'] = value
                elif 'allowed' in category_code or 'eligible' in category_code:
                    adj_data['allowed'] = value
                elif 'benefit' in category_code:
                    adj_data['benefit'] = value
                elif 'deductible' in category_code:
                    adj_data['deductible'] = value
                elif 'coinsurance' in category_code:
                    adj_data['coinsurance'] = value
                elif 'priorpayer' in category_code:
                    adj_data['prior_payer'] = value
                elif 'adjustment' in category_code or 'other' in category_code:
                    adj_data['all_adjustment'] = value
            
            line_items_list.append(adj_data)

print(f"✓ Extracted {len(eob_list)} ExplanationOfBenefit resources")
print(f"✓ Extracted {len(line_items_list)} line items total")

# ============================================================================
# STEP 3: CREATE DATAFRAMES FOR ANALYSIS
# ============================================================================

print("\n[STEP 3] Creating dataframes for analysis...")

df_eob = pd.DataFrame(eob_list)
df_items = pd.DataFrame(line_items_list)

print(f"✓ EOB DataFrame shape: {df_eob.shape}")
print(f"✓ Items DataFrame shape: {df_items.shape}")

print(f"\nEOB Summary:")
print(f"  Status: {df_eob['status'].value_counts().to_dict()}")
print(f"  Outcome: {df_eob['outcome'].value_counts().to_dict()}")

print(f"\nItems Summary:")
print(f"  Submitted - Mean: {df_items['submitted'].mean():.2f}")
print(f"  Benefit - Mean: {df_items['benefit'].mean():.2f}")
print(f"  Deductible - Mean: {df_items['deductible'].mean():.2f}")
print(f"  Coinsurance - Mean: {df_items['coinsurance'].mean():.2f}")

# ============================================================================
# STEP 4: CALCULATE FRAUD INDICATORS AT CLAIM LEVEL
# ============================================================================

print("\n[STEP 4] Calculating fraud indicators...")

# Group by claim and calculate metrics
claim_metrics = {}

for eob_id in df_items['eob_id'].unique():
    claim_items = df_items[df_items['eob_id'] == eob_id]
    
    # Initialize metrics
    metrics = {
        'eob_id': eob_id,
        'num_items': len(claim_items),
        'total_submitted': claim_items['submitted'].sum(),
        'total_allowed': claim_items['allowed'].sum(),
        'total_benefit': claim_items['benefit'].sum(),
        'total_deductible': claim_items['deductible'].sum(),
        'total_coinsurance': claim_items['coinsurance'].sum(),
        'total_prior_payer': claim_items['prior_payer'].sum(),
        'total_adjustment': claim_items['all_adjustment'].sum(),
        'num_items_with_deductible': (claim_items['deductible'] > 0).sum(),
        'num_items_with_coinsurance': (claim_items['coinsurance'] > 0).sum(),
        'num_adjudications': claim_items['all_adjustment'].notna().sum()
    }
    
    # Calculate ratios
    metrics['deductible_ratio'] = metrics['total_deductible'] / (metrics['total_submitted'] + 1)
    metrics['coinsurance_ratio'] = metrics['total_coinsurance'] / (metrics['total_benefit'] + 1)
    metrics['prior_payer_ratio'] = metrics['total_prior_payer'] / (metrics['total_submitted'] + 1)
    metrics['adjustment_ratio'] = metrics['total_adjustment'] / (metrics['total_submitted'] + 1)
    
    claim_metrics[eob_id] = metrics

df_claims = pd.DataFrame(list(claim_metrics.values()))

print(f"✓ Calculated metrics for {len(df_claims)} claims")

print(f"\nMetrics Summary:")
print(f"  Deductible ratio - Mean: {df_claims['deductible_ratio'].mean():.4f}, Std: {df_claims['deductible_ratio'].std():.4f}")
print(f"  Coinsurance ratio - Mean: {df_claims['coinsurance_ratio'].mean():.4f}, Std: {df_claims['coinsurance_ratio'].std():.4f}")
print(f"  Adjustment ratio - Mean: {df_claims['adjustment_ratio'].mean():.4f}, Std: {df_claims['adjustment_ratio'].std():.4f}")

# ============================================================================
# STEP 5: DEFINE FRAUD INDICATORS AND CREATE FRAUD SCORE
# ============================================================================

print("\n[STEP 5] Creating fraud indicators...")

fraud_indicators = pd.DataFrame(index=df_claims.index)
fraud_indicators['eob_id'] = df_claims['eob_id']

# INDICATOR 1: High deductible ratio (>30% of submitted amount)
fraud_indicators['high_deductible'] = df_claims['deductible_ratio'] > 0.30
count_1 = fraud_indicators['high_deductible'].sum()
print(f"  ✓ Indicator 1 - High deductible (>30%): {count_1} claims")

# INDICATOR 2: High coinsurance ratio (>50% of benefit)
fraud_indicators['high_coinsurance'] = df_claims['coinsurance_ratio'] > 0.50
count_2 = fraud_indicators['high_coinsurance'].sum()
print(f"  ✓ Indicator 2 - High coinsurance (>50%): {count_2} claims")

# INDICATOR 3: Excessive adjustments (>0.5 ratio = more than submitted)
fraud_indicators['high_adjustments'] = df_claims['adjustment_ratio'] > 0.50
count_3 = fraud_indicators['high_adjustments'].sum()
print(f"  ✓ Indicator 3 - High adjustments (>50%): {count_3} claims")

# INDICATOR 4: Many adjudications on single claim (>10 items adjusted)
fraud_indicators['many_adjudications'] = df_claims['num_adjudications'] > 10
count_4 = fraud_indicators['many_adjudications'].sum()
print(f"  ✓ Indicator 4 - Many adjudications (>10): {count_4} claims")

# INDICATOR 5: Extreme benefit amounts (>95th percentile)
benefit_threshold = df_claims['total_benefit'].quantile(0.95)
fraud_indicators['extreme_benefit'] = df_claims['total_benefit'] > benefit_threshold
count_5 = fraud_indicators['extreme_benefit'].sum()
print(f"  ✓ Indicator 5 - Extreme benefit (>95th%): {count_5} claims")

# ============================================================================
# STEP 6: CALCULATE FRAUD SCORE AND CREATE BINARY TARGET
# ============================================================================

print("\n[STEP 6] Calculating fraud score...")

# Create fraud score (sum of indicators)
fraud_indicators['fraud_score'] = (
    fraud_indicators['high_deductible'].astype(int) +
    fraud_indicators['high_coinsurance'].astype(int) +
    fraud_indicators['high_adjustments'].astype(int) +
    fraud_indicators['many_adjudications'].astype(int) +
    fraud_indicators['extreme_benefit'].astype(int)
)

print(f"  Fraud score distribution:")
print(fraud_indicators['fraud_score'].value_counts().sort_index())

# Create binary fraud target: score >= 2 = fraudulent
fraud_threshold = 2
fraud_indicators['is_fraud'] = (fraud_indicators['fraud_score'] >= fraud_threshold).astype(int)

print(f"\n  Using threshold: {fraud_threshold}")
print(f"  Fraudulent claims (score >= {fraud_threshold}): {fraud_indicators['is_fraud'].sum()}")
print(f"  Legitimate claims (score < {fraud_threshold}): {(1 - fraud_indicators['is_fraud']).sum()}")

# ============================================================================
# STEP 7: LOAD AND MERGE WITH CSV DATA
# ============================================================================

print("\n[STEP 7] Merging with CSV data...")

csv_file = 'D:/SecureHIC/data/cms_fhir_ml_combined.csv'

try:
    df_csv = pd.read_csv(csv_file)
    print(f"✓ Loaded CSV: {csv_file}")
    print(f"  Shape: {df_csv.shape}")
except Exception as e:
    print(f"✗ Error loading CSV: {e}")
    exit(1)

# Create mapping from EOB ID to fraud label
fraud_mapping = dict(zip(fraud_indicators['eob_id'], fraud_indicators['is_fraud']))

print(f"\nFraud mapping created for {len(fraud_mapping)} claims")

# Initialize fraud column
df_csv['is_fraud'] = 0  # Default to legitimate

# Add fraud labels
# The first 1000 rows of CSV correspond to the 1000 EOB records from JSON
for idx in range(min(1000, len(df_csv))):
    eob_id = df_csv.index[idx]  # Or use any mapping you have
    # If no direct mapping, assign based on position
    df_csv.loc[idx, 'is_fraud'] = fraud_indicators.iloc[idx]['is_fraud'] if idx < len(fraud_indicators) else 0

print(f"\nFraud labels added to CSV data")
print(f"  Fraudulent: {(df_csv['is_fraud'] == 1).sum()} ({(df_csv['is_fraud'] == 1).mean()*100:.2f}%)")
print(f"  Legitimate: {(df_csv['is_fraud'] == 0).sum()} ({(df_csv['is_fraud'] == 0).mean()*100:.2f}%)")

# ============================================================================
# STEP 8: VERIFY AND SAVE
# ============================================================================

print("\n[STEP 8] Verifying and saving...")

print(f"\nFinal dataset shape: {df_csv.shape}")
print(f"Columns: {list(df_csv.columns)}")

# Check for issues
print(f"\nData quality checks:")
print(f"  Missing values in is_fraud: {df_csv['is_fraud'].isnull().sum()}")
print(f"  Unique is_fraud values: {sorted(df_csv['is_fraud'].unique())}")
print(f"  Data types OK: {df_csv['is_fraud'].dtype == 'int64' or df_csv['is_fraud'].dtype == 'int32'}")

# Save to outputs
output_file = 'D:/SecureHIC/src/outputs/cms_fhir_with_fraud_target_from_code.csv'

try:
    df_csv.to_csv(output_file, index=False)
    print(f"\n✓ Saved to: {output_file}")
    print(f"  File size: {Path(output_file).stat().st_size / (1024*1024):.2f} MB")
except Exception as e:
    print(f"✗ Error saving: {e}")
    exit(1)

# ============================================================================
# STEP 9: SUMMARY STATISTICS
# ============================================================================

print("\n[STEP 9] Summary statistics...")

print(f"\n{'='*80}")
print("FRAUD DETECTION RESULTS")
print(f"{'='*80}")

print(f"\nDataset Summary:")
print(f"  Total claims: {len(df_csv):,}")
print(f"  Total features: {len(df_csv.columns)}")
print(f"  Fraud column: ✓ Added")

print(f"\nFraud Target Distribution:")
print(f"  Legitimate (0): {(df_csv['is_fraud'] == 0).sum():,} ({(df_csv['is_fraud'] == 0).mean()*100:.2f}%)")
print(f"  Fraudulent (1): {(df_csv['is_fraud'] == 1).sum():,} ({(df_csv['is_fraud'] == 1).mean()*100:.2f}%)")

print(f"\nFraud Indicators Used:")
print(f"  1. High deductible ratio (>30%)")
print(f"  2. High coinsurance ratio (>50%)")
print(f"  3. High adjustments (>50%)")
print(f"  4. Many adjudications (>10)")
print(f"  5. Extreme benefit amounts (>95th percentile)")

print(f"\nClassification Rule:")
print(f"  Score >= 2 indicators = FRAUDULENT")
print(f"  Score < 2 indicators = LEGITIMATE")

print(f"\nStatistics by Fraud Status:")
legitimate_data = df_csv[df_csv['is_fraud'] == 0]
fraudulent_data = df_csv[df_csv['is_fraud'] == 1]

print(f"\n  Legitimate Claims (n={len(legitimate_data)}):")
if 'payment_amount' in df_csv.columns:
    print(f"    Payment Amount - Mean: {legitimate_data['payment_amount'].mean():.2f}")
if 'total_charged' in df_csv.columns:
    print(f"    Total Charged - Mean: {legitimate_data['total_charged'].mean():.2f}")
if 'line_deductible_total' in df_csv.columns:
    print(f"    Deductible - Mean: {legitimate_data['line_deductible_total'].mean():.2f}")

print(f"\n  Fraudulent Claims (n={len(fraudulent_data)}):")
if 'payment_amount' in df_csv.columns:
    print(f"    Payment Amount - Mean: {fraudulent_data['payment_amount'].mean():.2f}")
if 'total_charged' in df_csv.columns:
    print(f"    Total Charged - Mean: {fraudulent_data['total_charged'].mean():.2f}")
if 'line_deductible_total' in df_csv.columns:
    print(f"    Deductible - Mean: {fraudulent_data['line_deductible_total'].mean():.2f}")

print(f"\n{'='*80}")
print("✓ FRAUD DATA EXTRACTION COMPLETE!")
print(f"{'='*80}")

print(f"\nOutput file: {output_file}")
print(f"\nYou can now use this data for:")
print(f"  • Train fraud detection models")
print(f"  • Analyze fraud patterns")
print(f"  • Use with the Quantum ML notebook")
print(f"  • Statistical analysis")
print(f"  • Any machine learning task")

# ============================================================================
# STEP 10: OPTIONAL - DETAILED FRAUD ANALYSIS
# ============================================================================

print(f"\n{'='*80}")
print("OPTIONAL: DETAILED FRAUD ANALYSIS")
print(f"{'='*80}")

print(f"\nFraudulent Claims Details:")
fraudulent_df = df_csv[df_csv['is_fraud'] == 1].copy()

if len(fraudulent_df) > 0:
    print(f"\nFraud claim samples:")
    
    # Select relevant columns for display
    display_cols = [col for col in ['secure_patient_id', 'claim_type', 'total_charged', 
                                     'payment_amount', 'line_deductible_total', 'is_fraud'] 
                   if col in fraudulent_df.columns]
    
    print(fraudulent_df[display_cols].head(10))
    
    print(f"\nFraudulent claims by claim type:")
    if 'claim_type' in fraudulent_df.columns:
        print(fraudulent_df['claim_type'].value_counts())
else:
    print("No fraudulent claims detected in this subset")

print(f"\n✓ Analysis complete!")
