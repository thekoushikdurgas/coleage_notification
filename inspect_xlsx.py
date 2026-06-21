import pandas as pd
import os

file_path = r"E:\ayan\contact360\docs\codebases\ideas\coleage_notification\inputs\College-ALL COLLEGE.xlsx"

print("Checking file existence...", os.path.exists(file_path))
if os.path.exists(file_path):
    # Read sheet 'College-' with header=2 (the third row is the header)
    df = pd.read_excel(file_path, sheet_name='College-', header=2, nrows=5)
    print("\nActual Columns (from row index 2):\n", df.columns.tolist())
    print("\nFirst Row Details:\n")
    for col in df.columns:
        print(f"  {col}: {df.loc[0, col]}")
