import os
import sys
import pandas as pd
from datetime import datetime
import time

# Add the project root to python path to import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import db, Organization

def seed_database(app=None):
    """
    Seeds the database with organizations from the Excel input files.

    Parameters
    ----------
    app : Flask app instance, optional
        Pass the already-created app so this function never calls create_app()
        a second time.  When run as a standalone script (``python seed.py``),
        leave it as None and the function will create its own app.
    """
    if app is None:
        # Standalone / CLI usage only – import here to avoid circular issues
        from app import create_app as _create_app
        app = _create_app()

    with app.app_context():
        # Tables must already exist (caller is responsible for db.create_all())
        # We intentionally do NOT call db.drop_all() here so that partial data
        # is never accidentally destroyed on a restart.
        print("Starting database seed (tables already created by caller)...")
        
        inputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inputs')
        univ_path = os.path.join(inputs_dir, 'University-ALL UNIVERSITIES.xlsx')
        stand_path = os.path.join(inputs_dir, 'Standalone-ALL STANDALONE.xlsx')
        college_path = os.path.join(inputs_dir, 'College-ALL COLLEGE.xlsx')
        
        # Verify files exist
        for path in [univ_path, stand_path, college_path]:
            if not os.path.exists(path):
                print(f"Error: Required Excel file not found at: {path}")
                return
                
        start_time = time.time()
        colleges_to_insert = []
        
        def parse_year(val):
            if val is not None:
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    pass
            return None

        # 1. Read Universities
        print(f"Reading University data from: {univ_path}")
        try:
            univ_df = pd.read_excel(univ_path, sheet_name='University-', header=2)
            univ_df = univ_df.where(pd.notnull(univ_df), None)
            print(f"University read complete. Rows: {len(univ_df)}")
        except Exception as e:
            print(f"Error reading University Excel file: {e}")
            return
            
        university_map = {}
        for idx, row in univ_df.iterrows():
            aishe = row.get('Aishe Code')
            name = row.get('Name')
            if aishe:
                aishe = str(aishe).strip()
            if name:
                name = str(name).strip()
                
            if aishe and name:
                university_map[aishe] = name
                
            colleges_to_insert.append({
                'aishe_code': aishe,
                'name': name,
                'category': 'university',
                'state': row.get('State'),
                'district': row.get('District'),
                'website': row.get('Website'),
                'year_of_establishment': parse_year(row.get('Year Of Establishment')),
                'location_type': row.get('Location'),
                'is_tracked': True
            })

        # 2. Read Standalones
        print(f"Reading Standalone data from: {stand_path}")
        try:
            stand_df = pd.read_excel(stand_path, sheet_name='Standalone-', header=2)
            stand_df = stand_df.where(pd.notnull(stand_df), None)
            print(f"Standalone read complete. Rows: {len(stand_df)}")
        except Exception as e:
            print(f"Error reading Standalone Excel file: {e}")
            return
            
        for idx, row in stand_df.iterrows():
            colleges_to_insert.append({
                'aishe_code': row.get('Aishe Code'),
                'name': row.get('Name'),
                'category': 'standalone',
                'state': row.get('State'),
                'district': row.get('District'),
                'year_of_establishment': parse_year(row.get('Year Of Establishment')),
                'location_type': row.get('Location'),
                'college_type': row.get('Standalone Type'),
                'management': row.get('Manegement'),
                'is_tracked': True
            })

        # 3. Read Colleges
        print(f"Reading College data from: {college_path}")
        try:
            coll_df = pd.read_excel(college_path, sheet_name='College-', header=2)
            coll_df = coll_df.where(pd.notnull(coll_df), None)
            print(f"College read complete. Rows: {len(coll_df)}")
        except Exception as e:
            print(f"Error reading College Excel file: {e}")
            return
            
        for idx, row in coll_df.iterrows():
            univ_aishe = row.get('University Aishe Code')
            univ_name = None
            if univ_aishe:
                univ_aishe = str(univ_aishe).strip()
                univ_name = university_map.get(univ_aishe, f"University ({univ_aishe})")
                
            colleges_to_insert.append({
                'aishe_code': row.get('Aishe Code'),
                'name': row.get('Name'),
                'category': 'college',
                'state': row.get('State'),
                'district': row.get('District'),
                'website': row.get('Website'),
                'year_of_establishment': parse_year(row.get('Year Of Establishment')),
                'location_type': row.get('Location'),
                'college_type': row.get('College Type'),
                'management': row.get('Manegement'),
                'university_name': univ_name,
                'is_tracked': True
            })

        # Seed standard Boards
        print("Adding standard educational boards...")
        boards = [
            {"name": "CBSE - Central Board of Secondary Education", "aishe_code": "BOARD-CBSE", "website": "cbse.gov.in"},
            {"name": "CISCE - Council for the Indian School Certificate Examinations", "aishe_code": "BOARD-CISCE", "website": "cisce.org"},
            {"name": "JAC - Jharkhand Academic Council", "aishe_code": "BOARD-JAC", "website": "jac.jharkhand.gov.in"},
            {"name": "BSEB - Bihar School Examination Board", "aishe_code": "BOARD-BSEB", "website": "biharboardonline.bihar.gov.in"},
            {"name": "UP Board - Board of High School and Intermediate Education Uttar Pradesh", "aishe_code": "BOARD-UP", "website": "upmsp.edu.in"},
            {"name": "Rajasthan Board - Board of Secondary Education Rajasthan", "aishe_code": "BOARD-BSER", "website": "rajeduboard.rajasthan.gov.in"},
            {"name": "MP Board - Board of Secondary Education Madhya Pradesh", "aishe_code": "BOARD-MPSE", "website": "mpbse.nic.in"},
            {"name": "Haryana Board - Board of School Education Haryana", "aishe_code": "BOARD-BSEH", "website": "bseh.org.in"},
            {"name": "Punjab Board - Punjab School Education Board", "aishe_code": "BOARD-PSEB", "website": "pseb.ac.in"},
            {"name": "Maharashtra Board - Maharashtra State Board of Secondary and Higher Secondary Education", "aishe_code": "BOARD-MSBSHSE", "website": "mahahsscboard.in"},
            {"name": "Karnataka Board - Karnataka School Examination and Assessment Board", "aishe_code": "BOARD-KSEAB", "website": "kseab.karnataka.gov.in"},
            {"name": "Tamil Nadu Board - Directorate of Government Examinations Tamil Nadu", "aishe_code": "BOARD-TNDGE", "website": "dge.tn.gov.in"},
            {"name": "Telangana Board - Telangana Board of Secondary Education", "aishe_code": "BOARD-TSE", "website": "bse.telangana.gov.in"},
            {"name": "Andhra Pradesh Board - Board of Secondary Education Andhra Pradesh", "aishe_code": "BOARD-BSEAP", "website": "bse.ap.gov.in"},
            {"name": "Kerala Board - Board of Public Examinations Kerala", "aishe_code": "BOARD-KBPE", "website": "keralapareekshabhavan.in"}
        ]
        
        for board in boards:
            colleges_to_insert.append({
                'aishe_code': board['aishe_code'],
                'name': board['name'],
                'category': 'board',
                'website': board['website'],
                'state': board['name'].split(" ")[-2] if "Board" in board['name'] else None,
                'is_tracked': True
            })
            
        # Seed standard Regulators
        print("Adding standard regulatory bodies...")
        regulators = [
            {"name": "AICTE - All India Council for Technical Education", "aishe_code": "REG-AICTE", "website": "aicte-india.org"},
            {"name": "UGC - University Grants Commission", "aishe_code": "REG-UGC", "website": "ugc.gov.in"},
            {"name": "NTA - National Testing Agency", "aishe_code": "REG-NTA", "website": "nta.ac.in"},
            {"name": "Ministry of Education (MoE)", "aishe_code": "REG-MOE", "website": "education.gov.in"},
            {"name": "NMC - National Medical Commission", "aishe_code": "REG-NMC", "website": "nmc.org.in"},
            {"name": "DCI - Dental Council of India", "aishe_code": "REG-DCI", "website": "dciindia.gov.in"},
            {"name": "PCI - Pharmacy Council of India", "aishe_code": "REG-PCI", "website": "pci.nic.in"},
            {"name": "BCI - Bar Council of India", "aishe_code": "REG-BCI", "website": "barcouncilofindia.org"},
            {"name": "NCTE - National Council for Teacher Education", "aishe_code": "REG-NCTE", "website": "ncte.gov.in"},
            {"name": "NAAC - National Assessment and Accreditation Council", "aishe_code": "REG-NAAC", "website": "naac.gov.in"},
            {"name": "NBA - National Board of Accreditation", "aishe_code": "REG-NBA", "website": "nbaindia.org"},
            {"name": "AIU - Association of Indian Universities", "aishe_code": "REG-AIU", "website": "aiu.ac.in"},
            {"name": "NCERT - National Council of Educational Research and Training", "aishe_code": "REG-NCERT", "website": "ncert.nic.in"}
        ]
        
        for reg in regulators:
            colleges_to_insert.append({
                'aishe_code': reg['aishe_code'],
                'name': reg['name'],
                'category': 'regulatory_body',
                'website': reg['website'],
                'is_tracked': True
            })

        # Bulk insert
        print("Inserting records into database...")
        insert_start = time.time()
        
        # Batch insert to avoid memory overload and optimize SQLite transaction boundaries
        batch_size = 5000
        for i in range(0, len(colleges_to_insert), batch_size):
            batch = colleges_to_insert[i:i+batch_size]
            db.session.bulk_insert_mappings(Organization, batch)
            db.session.commit()
            print(f"  Inserted {min(i+batch_size, len(colleges_to_insert))} / {len(colleges_to_insert)} records...")
            
        print(f"Database seeding completed successfully in {time.time() - start_time:.2f} seconds.")
        print(f"Total organizations registered: {Organization.query.count()}")

if __name__ == '__main__':
    # Standalone execution: create the app, create tables, then seed
    from app import create_app
    _app = create_app()
    with _app.app_context():
        db.drop_all()     # safe to wipe when run manually via CLI
        db.create_all()
    seed_database(_app)
